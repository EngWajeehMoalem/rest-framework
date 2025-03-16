import jwt
import datetime
from odoo import models, api, fields, _
from odoo.http import request
from odoo.exceptions import AccessDenied, UserError


class ResUsers(models.Model):
  _inherit = "res.users"

  @api.model
  def encode_jwt_token(self, user_id):
    """Generate a JWT token for the given user ID."""
    user = self.sudo().browse(user_id)
    if not user:
      raise UserError(_("User not found"))

    # Fetch JWT Secret and Expiration from system parameters
    jwt_secret = request.env['ir.config_parameter'].sudo().get_param('jwt_secret', 'default_secret')
    jwt_expiration = int(request.env['ir.config_parameter'].sudo().get_param(
        'jwt_expiration', 3600))

    # Create JWT payload
    payload = {
        'uid': user.id,
        'login': user.login,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=jwt_expiration),
        'iat': datetime.datetime.utcnow()
    }
    # Encode and return the JWT token
    return {
        "type": "bearer",
        "access_token": jwt.encode(payload, jwt_secret, algorithm="HS256"),
        "expires_at": str(payload['exp']),
        "expires_in": jwt_expiration
    }

  @api.model
  def decode_jwt_token(self, token):
    """Decode and verify a JWT token."""
    jwt_secret = request.env['ir.config_parameter'].sudo().get_param('jwt_secret', 'default_secret')
    try:
      payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
      return payload  # Returns decoded payload (user data)
    except jwt.ExpiredSignatureError:
      raise AccessDenied(_("JWT token has expired"))
    except jwt.InvalidTokenError:
      raise AccessDenied(_("Invalid JWT token"))

  @api.model
  def jwt_login(self, login, password):
    """Authenticate user and return JWT token."""
    user = self.sudo().search([('login', '=', login)], limit=1)
    if not user:
      raise AccessDenied(_("Invalid login or password"))

    try:
      user._check_credentials(password, self.env)
    except AccessDenied:
      raise AccessDenied(_("Invalid login or password"))

    # Generate JWT token for the authenticated user
    token = self.encode_jwt_token(user.id)

    return {"token": token, "user_id": user.id, "login": user.login, "name": user.name}



  