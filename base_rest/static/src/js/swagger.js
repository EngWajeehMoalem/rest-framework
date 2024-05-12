/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import SwaggerUi from '@base_rest/js/swagger_ui';

publicWidget.registry.Swagger = publicWidget.Widget.extend({
  selector: "#swagger-ui",
  start: function () {
      var def = this._super.apply(this, arguments);      
      var swagger_ui = new SwaggerUi("#swagger-ui");
      swagger_ui.start();
      return def;
  },
});



