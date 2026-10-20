{
    "name": "Warranty Management",
    "summary": "Manage product warranties, claims, invoice and supplier-bill coverage",
    "description": """
Warranty management for Odoo Community and Enterprise.

This module provides:
- warranty types
- warranty policies
- warranty coverage records
- warranty claims
- warranty history and audit trail
- expiry notifications
- duplicate active warranty prevention by lot and serial number
- customer warranties from invoices and supplier warranties from vendor bills
- purchase order traceability and warranty dashboard
    """,
    "author": "Ajith",
    "category": "Warranty",
    "website": "https://ajith.dev",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["base", "mail", "product", "stock", "account", "purchase", "web"],
    "data": [
        "security/warranty_security.xml",
        "security/ir.model.access.csv",
        "security/account_warranty_access.csv",
        "data/warranty_sequence.xml",
        "data/warranty_cron.xml",
        "views/warranty_type_views.xml",
        "views/warranty_policy_views.xml",
        "views/warranty_coverage_views.xml",
        "views/warranty_claim_views.xml",
        "views/warranty_history_views.xml",
        "views/product_template_views.xml",
        "views/warranty_menus.xml",
        "views/account_move_views.xml",
        "wizard/account_warranty_wizard_views.xml",
        "views/account_warranty_coverage_views.xml",
        "views/purchase_order_views.xml",
        "views/purchase_warranty_coverage_views.xml",
        "views/warranty_dashboard_menu.xml",
    ],
    "application": True,
    "images": ["static/description/icon.png", "static/description/banner.png"],
    "assets": {
        "web.assets_backend": [
            "warranty_mgmt/static/src/css/warranty_dashboard.css",
            "warranty_mgmt/static/src/js/warranty_dashboard.js",
            "warranty_mgmt/static/src/xml/warranty_dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False
}
