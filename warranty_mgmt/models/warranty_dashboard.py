from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

# How coverages map to the two business flows the dashboard splits on. Uses the
# core `source_model` field so the dashboard needs no dependency on the helpdesk
# or purchase connector modules.
SOURCE_LABELS = {
    "sale": "Customer Invoice",
    "purchase": "Supplier Bill",
    "repair": "Repair",
    "other": "Other",
}

# Number of days ahead that counts as "expiring soon".
EXPIRY_WINDOW_DAYS = 30


class WarrantyDashboard(models.AbstractModel):
    """Data provider for the Warranty Dashboard.

    A single RPC (`get_warranty_dashboard_data`) returns every KPI, list and
    chart the OWL frontend needs. Aggregations use `_read_group` and lists are
    limited for performance.
    """

    _name = "warranty.dashboard"
    _description = "Warranty Dashboard Helper"

    @api.model
    def get_warranty_dashboard_data(self):
        if not self.env.user.has_group("warranty_mgmt.group_warranty_user"):
            raise AccessError(_("You need Warranty User access to open the dashboard."))
        Coverage = self.env["warranty.coverage"]
        Claim = self.env["warranty.claim"]
        today = fields.Date.context_today(self)
        soon = today + relativedelta(days=EXPIRY_WINDOW_DAYS)

        expiring_domain = [
            ("state", "=", "active"),
            ("expiry_date", ">=", today),
            ("expiry_date", "<=", soon),
        ]

        # ------------------------------------------------------------------
        # KPI cards
        # ------------------------------------------------------------------
        kpis = {
            "active": Coverage.search_count([("state", "=", "active")]),
            "expiring_soon": Coverage.search_count(expiring_domain),
            "expired": Coverage.search_count([("state", "=", "expired")]),
            "sale_total": Coverage.search_count([("warranty_origin", "=", "sale")]),
            "purchase_total": Coverage.search_count([("warranty_origin", "=", "purchase")]),
            "total_coverages": Coverage.search_count([]),
            "open_claims": Claim.search_count([("state", "in", ("submitted", "approved"))]),
            "total_claims": Claim.search_count([]),
            "expiry_window": EXPIRY_WINDOW_DAYS,
        }

        # ------------------------------------------------------------------
        # Charts
        # ------------------------------------------------------------------
        coverage_state_labels = dict(Coverage._fields["state"].selection)
        coverage_by_state = [
            {"label": coverage_state_labels.get(state, state or "?"), "count": count, "key": state}
            for state, count in Coverage._read_group([], ["state"], ["__count"])
        ]

        claim_state_labels = dict(Claim._fields["state"].selection)
        claims_by_status = [
            {"label": claim_state_labels.get(state, state or "?"), "count": count, "key": state}
            for state, count in Claim._read_group([], ["state"], ["__count"])
        ]

        source_split = [
            {"label": SOURCE_LABELS.get(origin, "Other"), "count": count, "key": origin or "other"}
            for origin, count in Coverage._read_group([], ["warranty_origin"], ["__count"])
        ]

        # ------------------------------------------------------------------
        # Expiring-soon list
        # ------------------------------------------------------------------
        expiring_list = []
        for cov in Coverage.search_read(
            expiring_domain,
                fields=["name", "product_id", "partner_id", "expiry_date", "warranty_origin"],
            order="expiry_date asc",
            limit=12,
        ):
            expiry = fields.Date.to_date(cov["expiry_date"])
            expiring_list.append({
                "id": cov["id"],
                "name": cov["name"],
                "product": cov["product_id"][1] if cov["product_id"] else "",
                "partner": cov["partner_id"][1] if cov["partner_id"] else "",
                "expiry_date": str(expiry or ""),
                "days_left": (expiry - today).days if expiry else 0,
                "source": SOURCE_LABELS.get(cov["warranty_origin"], "Other"),
            })

        # ------------------------------------------------------------------
        # Recent claims list
        # ------------------------------------------------------------------
        recent_claims = []
        for claim in Claim.search_read(
            [],
            fields=["name", "product_id", "state", "coverage_id"],
            order="create_date desc",
            limit=12,
        ):
            recent_claims.append({
                "id": claim["id"],
                "name": claim["name"],
                "product": claim["product_id"][1] if claim["product_id"] else "",
                "state": claim["state"],
                "status": claim_state_labels.get(claim["state"], claim["state"]),
                "coverage": claim["coverage_id"][1] if claim["coverage_id"] else "",
            })

        # ------------------------------------------------------------------
        # Attention list
        # ------------------------------------------------------------------
        alerts = []
        for cov in Coverage.search([("state", "=", "expired")], order="expiry_date desc", limit=4):
            alerts.append({
                "icon": "⚠️",
                "message": "Expired: %s — %s" % (cov.name, cov.product_id.display_name or ""),
                "model": "warranty.coverage",
                "res_id": cov.id,
            })
        for claim in Claim.search([("state", "=", "submitted")], order="create_date desc", limit=4):
            alerts.append({
                "icon": "📋",
                "message": "Claim awaiting approval: %s" % claim.name,
                "model": "warranty.claim",
                "res_id": claim.id,
            })

        return {
            "kpis": kpis,
            "coverage_by_state": coverage_by_state,
            "claims_by_status": claims_by_status,
            "source_split": source_split,
            "expiring_list": expiring_list,
            "recent_claims": recent_claims,
            "alerts": alerts,
        }
