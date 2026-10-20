Warranty Management
===================

Warranty Management can automatically create product warranty coverage when
eligible customer invoices and vendor bills are posted. Configure a policy
default, override it per product, and manage lots, claims, expiry notifications,
purchase traceability, and dashboard reporting.

Requirements
------------

* Odoo 19 Community or Enterprise
* Accounting and Purchase applications

Customer warranties
-------------------

Post a customer invoice and select **Give Customer Warranty**. Choose the
policy and coverage dates for each eligible product. The created coverage is
linked to its invoice and invoice line.

Automatic registration
----------------------

Enable **Automatic Creation** on a policy, then enable warranty handling on
products and set **Warranty Registration** to **Use Policy Setting**, **Manual**,
or **Automatic**. Automatic coverage is created after posting a customer invoice
or vendor bill. The product setting can override the selected policy setting.
Tracked products use one record per linked lot or serial; if no lot is linked,
coverage is created at product level. Lines that lack a matching policy or an
available start date are skipped and explained in document chatter.

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
