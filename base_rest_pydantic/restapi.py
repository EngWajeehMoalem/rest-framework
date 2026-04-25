# Copyright 2021 ACSONE SA/NV
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
import json

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.base_rest import restapi

from pydantic import BaseModel, ValidationError


class RESTValidationError(UserError):
  errors = []

  def __init__(self, message, errors=None):
    super().__init__(message)
    self.errors = errors or []


def replace_ref_in_schema(item, original_schema):
  if isinstance(item, list):
    return [replace_ref_in_schema(i, original_schema) for i in item]
  elif isinstance(item, dict):
    if list(item.keys()) == ["$ref"]:
      schema = item["$ref"].split("/")[-1]
      return {"$ref": f"#/components/schemas/{schema}"}
    else:
      return {key: replace_ref_in_schema(i, original_schema) for key, i in item.items()}
  else:
    return item


class PydanticModel(restapi.RestMethodParam):

  def __init__(self, cls: BaseModel):
    """
        :param name: The pydantic model name
        """
    if not issubclass(cls, BaseModel):
      raise TypeError(f"{cls} is not a subclass of odoo.addons.pydantic.models.BaseModel")
    self._model_cls = cls

  def from_params(self, service, params):
    try:
      return self._model_cls(**params)
    except ValidationError as ve:
      errors = []
      for error in ve.errors():
        errors.append({
            "field": error.get("loc", ["unknown"])[0],  # Extract field name
            "rule": error.get("type", "invalid"),
            "message": error.get("msg", "Invalid input.")
        })
      raise RESTValidationError(_(
          "One or more inputs are invalid. Please check your request and try again."
      ),
                                errors=errors) from ve

  def to_response(self, service, result):
    # do we really need to validate the instance????
    json_dict = result.model_dump()
    orm_mode = result.model_config.get("from_attributes", None)
    to_validate = json_dict if orm_mode else result.model_dump(by_alias=True)
    # Ensure that to_validate is under json format
    try:
      json.loads(to_validate)
      to_validate_jsonified = to_validate
    except TypeError:
      to_validate_jsonified = json.dumps(to_validate)

    try:
      self._model_cls.model_validate_json(to_validate_jsonified)
    except ValidationError as validation_error:
      raise SystemError(_("Invalid Response")) from validation_error
    return json_dict

  def to_openapi_query_parameters(self, servic, spec):
    json_schema = self._model_cls.model_json_schema()
    parameters = []

    for prop, prop_spec in json_schema.get("properties", {}).items():

        params = {
            "name": prop,
            "in": "query",
            "required": prop in json_schema.get("required", []),
            "default": prop_spec.get("default"),
        }

        schema = {}

        # -------------------------
        # Handle type / unions
        # -------------------------
        if "type" in prop_spec:
            schema["type"] = prop_spec["type"]

        elif "anyOf" in prop_spec:
            # Pydantic v2 nullable/Union handling
            schema["anyOf"] = prop_spec["anyOf"]

        elif "oneOf" in prop_spec:
            schema["oneOf"] = prop_spec["oneOf"]

        elif "$ref" in prop_spec:
            schema["$ref"] = prop_spec["$ref"]

        # -------------------------
        # Enum support
        # -------------------------
        if "enum" in prop_spec:
            schema["enum"] = prop_spec["enum"]

        # -------------------------
        # Array support
        # -------------------------
        if prop_spec.get("type") == "array" and "items" in prop_spec:
            schema["items"] = prop_spec["items"]

        # -------------------------
        # Attach schema safely
        # -------------------------
        params["schema"] = schema if schema else prop_spec

        # -------------------------
        # Array query naming convention
        # -------------------------
        if prop_spec.get("type") == "array":
            params["name"] = f"{params['name']}[]"

        parameters.append(params)

    return parameters

  # TODO, we should probably get the spec as parameters. That should
  # allows to add the definition of a schema only once into the specs
  # and use a reference to the schema into the parameters
  def to_openapi_requestbody(self, service, spec):
    return {
        "content": {
            "application/json": {
                "schema": self.to_json_schema(service, spec, "input")
            }
        }
    }

  def to_openapi_responses(self, service, spec):
    return {
        "200": {
            "content": {
                "application/json": {
                    "schema": self.to_json_schema(service, spec, "output")
                }
            }
        }
    }

  def to_json_schema(self, service, spec, direction):
    schema = self._model_cls.model_json_schema(by_alias=False)
    schema_name = schema["title"]
    if schema_name not in spec.components.schemas:
      definitions = schema.pop("$defs", {})
      for name, sch in definitions.items():
        if name in spec.components.schemas:
          continue
        sch = replace_ref_in_schema(sch, sch)
        spec.components.schema(name, sch)
      schema = replace_ref_in_schema(schema, schema)
      spec.components.schema(schema_name, schema)
    return {"$ref": f"#/components/schemas/{schema_name}"}


class PydanticModelList(PydanticModel):

  def __init__(
      self,
      cls: BaseModel,
      min_items: int = None,
      max_items: int = None,
      unique_items: bool = None,
  ):
    """
        :param name: The pydantic model name
        :param min_items: A list instance is valid against "min_items" if its
                          size is greater than, or equal to, min_items.
                          The value MUST be a non-negative integer.
        :param max_items: A list instance is valid against "max_items" if its
                          size is less than, or equal to, max_items.
                          The value MUST be a non-negative integer.
        :param unique_items: Used to document that the list should only
                             contain unique items.
                             (Not enforced at validation time)
        """
    super().__init__(cls=cls)
    self._min_items = min_items
    self._max_items = max_items
    self._unique_items = unique_items

  def from_params(self, service, params):
    self._do_validate(params, "input")
    return [super(PydanticModelList, self).from_params(service, param) for param in params]

  def to_response(self, service, result):
    self._do_validate(result, "output")
    return [super(PydanticModelList, self).to_response(service=service, result=r) for r in result]

  def to_openapi_query_parameters(self, service, spec):
    raise NotImplementedError("List are not (?yet?) supported as query paramters")

  def _do_validate(self, values, direction):
    ExceptionClass = UserError if direction == "input" else SystemError
    if self._min_items is not None and len(values) < self._min_items:
      raise ExceptionClass(
          _(
              "BadRequest: Not enough items in the list (%(current)s < %(expected)s)",
              current=len(values),
              expected=self._min_items,
          )
      )
    if self._max_items is not None and len(values) > self._max_items:
      raise ExceptionClass(
          _(
              "BadRequest: Too many items in the list (%(current)s > %(expected)s)",
              current=len(values),
              expected=self._max_items,
          )
      )

  # TODO, we should probably get the spec as parameters. That should
  # allows to add the definition of a schema only once into the specs
  # and use a reference to the schema into the parameters
  def to_openapi_requestbody(self, service, spec):
    return {
        "content": {
            "application/json": {
                "schema": self.to_json_schema(service, spec, "input")
            }
        }
    }

  def to_openapi_responses(self, service, spec):
    return {
        "200": {
            "content": {
                "application/json": {
                    "schema": self.to_json_schema(service, spec, "output")
                }
            }
        }
    }

  def to_json_schema(self, service, spec, direction):
    json_schema = super().to_json_schema(service, spec, direction)
    json_schema = {"type": "array", "items": json_schema}
    if self._min_items is not None:
      json_schema["minItems"] = self._min_items
    if self._max_items is not None:
      json_schema["maxItems"] = self._max_items
    if self._unique_items is not None:
      json_schema["uniqueItems"] = self._unique_items
    return json_schema


restapi.PydanticModel = PydanticModel
restapi.PydanticModelList = PydanticModelList
