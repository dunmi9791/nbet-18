# NBET Branding (`nbet_brand`)

The NBET PDF letterhead. Companion to
[`theme_nbet`](../theme_nbet/README.md); each installs and works without the
other.

## What's in it

Registers an **NBET** document layout, selectable under
*Settings → General Settings → Companies → Document Layout*. Because it plugs
into `web.external_layout`, every QWeb report picks it up without being touched
individually — the `nbet_treasury` payment vouchers, `nbet_procurement`
purchase orders, invoices, and anything added later.

The letterhead carries the navy rule with a lime leader used as the masthead
device on the corporate site, navy section headings underlined in lime, and
table headers matching the site's market-data tables.

## Why this isn't part of `theme_nbet`

Odoo converts every `<template>` in a module whose name starts with `theme_`
into a `theme.ir.ui.view` (`odoo/tools/convert.py`, `_tag_template`). Those get
copied per website when the theme is activated and removed when it is switched
out.

That lifecycle breaks the letterhead: `report.layout.view_id` is a
`Many2one('ir.ui.view')`, so a `ref` to a template declared in a theme module
resolves to a `theme.ir.ui.view` id — a different table — and the record fails
to load.

Keeping it in a plain module means it stays a plain `ir.ui.view` with the
normal module lifecycle, and installs on databases without the Website app.

(Sign-in branding lives in `theme_nbet` instead: with Website installed,
`/web/login` renders through `website.layout`, so it genuinely is website
markup.)

## Install

```bash
odoo -d <db> -i nbet_brand --addons-path=/path/to/nbet-18,/path/to/odoo/addons
```

Then select the **NBET** layout under *Settings → General Settings → Document
Layout*. The letterhead pulls the logo, address, tagline and footer from the
company record, so fill those in there rather than editing the template.
