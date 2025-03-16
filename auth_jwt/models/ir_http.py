import logging

from odoo import models
from odoo.exceptions import AccessDenied
from odoo.http import request

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
  _inherit = "ir.http"

  @classmethod
  def _auth_method_jwt(cls):
    authorization = request.httprequest.environ.get("HTTP_AUTHORIZATION")
    if authorization:
      request.update_env(user=1)
      authorization = authorization.replace("Bearer ", "")
      decoded_token = request.env["res.users"].decode_jwt_token(authorization)
      if decoded_token:
        request._env = None
        request.update_env(user=decoded_token["uid"])
        return True
    _logger.error("Wrong HTTP_AUTHORIZATION, access denied")
    raise AccessDenied()
