Warranty Management
===================

Warranty Management centralizes product warranty policies, coverage records,
claims, expiry notifications, invoice and vendor bill registration, purchase
traceability, and dashboard reporting.

Requirements
------------

* Odoo 19 Community or Enterprise
* Accounting and Purchase applications

Customer warranties
-------------------

Post a customer invoice and select **Give Customer Warranty**. Choose the
policy and coverage dates for each eligible product. The created coverage is
linked to its invoice and invoice line.

Supplier warranties
-------------------

Post a vendor bill and select **Register Supplier Warranty**. Choose the
supplier policy and dates. When the bill line comes from a purchase order, its
coverage retains the purchase order and order line references.

Claims and expiry
-----------------

Warranty users submit claims; warranty managers approve, reject, and resolve
them. A scheduled action checks expiring and expired coverages and schedules
activities for responsible users and warranty managers.

Access control
--------------

Warranty access is restricted to assigned records for users and to enabled
companies for managers. Policy and type administration is reserved for
Warranty Admin users. History is created by application workflows and is
read-only.

Upgrade compatibility
---------------------

This addon uses the new technical name ``warranty_mgmt``. Existing databases
with the ``smr_warranty*`` addons require a separately planned and tested
migration; installing this addon alone does not migrate their data.
