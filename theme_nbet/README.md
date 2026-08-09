# NBET Theme (`theme_nbet`)

Odoo 18 website theme for Nigerian Bulk Electricity Trading Plc, built from the
design language of [www.nbet.com.ng](https://www.nbet.com.ng/).

## Brand tokens

Sampled from the corporate site's stylesheet (`assets/css/style2.css`):

| Token | Hex | Role |
|---|---|---|
| Navy | `#131e4a` | Masthead, footer, headings |
| Lime | `#85c226` | Primary accent, CTAs, the bolt in the logo |
| Deep green | `#016004` | Secondary green |
| Orange | `#fd824a` | Sparing highlight |
| Ice | `#f0fbff` | Alternating section background |

Type: **Roboto** for body, **Poppins** for headings — the pairing the corporate
site uses. Roboto ships with Odoo; Poppins is added to `$o-theme-font-configs`
in `static/src/scss/primary_variables.scss`.

Three palettes are registered, selectable under **Website → Customize → Theme
Colors**:

- `nbet-1` (default) — lime drives the CTAs, navy carries the chrome
- `nbet-2` — institutional; navy leads, lime reserved for emphasis
- `nbet-3` — the deeper green used on the market-data pages

## What's in it

**Design system** — colour palettes, font pairing, squared-off buttons and
inputs, softened shadows, and the header/footer defaults, applied through
Odoo's own theme variable contract (`web._assets_primary_variables`,
`web._assets_frontend_helpers`).

**Six snippets**, in an "NBET" category in the site builder's block panel:

| Snippet | What it is |
|---|---|
| `s_nbet_hero` | Full-bleed carousel with a navy scrim over photography |
| `s_nbet_quicklinks` | Card grid for PPAs, Market Rules, EPSRA, the mandate |
| `s_nbet_capacity` | The "00 MW" figures, counting up on scroll |
| `s_nbet_value_chain` | Generation → Bulk Trading → Transmission → Distribution |
| `s_nbet_leadership` | Board / executive management cards |
| `s_nbet_partners` | Greyscale logo strip that colours on hover |

**Header top bar** — contact details and social links above the navigation,
populated from the company record and website social fields rather than
hard-coded, so it stays correct without anyone editing the theme.

**Homepage and About Us** — the homepage fills `website.homepage`'s empty
`oe_structure`; About Us is created at `/about-us`. Both sit inside editable
regions, so the first edit in the site builder triggers Odoo's copy-on-write
and leaves these templates untouched as the fallback.

**Portal** — the customer/employee portal (including `nbet_hr_leave_portal`)
picks up the navy/lime treatment on cards, tables and headers.

**Sign-in** — the NBET lockup and a branded card on `/web/login`.

> This inherits `website.login_layout`, **not** `web.login_layout`. When the
> Website app is installed, `website.login_layout` (priority 20) runs
> `<xpath expr="t" position="replace">` against `web.login_layout`, discarding
> its entire body — card, company-logo block and `body_classname` — and
> re-rendering login through `website.layout`. Any view targeting
> `web.login_layout`'s original markup raises *"Element cannot be located in
> parent view"* at install. The resolved parent is just:
>
> ```xml
> <t t-call="website.layout">
>     <div class="oe_website_login_container" t-out="0"/>
> </t>
> ```

## Install

```bash
odoo -d <db> -i theme_nbet --addons-path=/path/to/nbet-18,/path/to/odoo/addons
```

Then **Website → Configuration → Settings → Theme**, pick *NBET Theme*.

Upload `static/src/img/nbet_logo.png` as the website logo under
**Website → Configuration → Settings**, and set the company phone, email and
social URLs so the header top bar fills in.

## Related

The PDF letterhead lives in **`nbet_brand`**, deliberately kept out of this
module: Odoo converts every template in a `theme_*` module into a
`theme.ir.ui.view`, but `report.layout.view_id` is a `Many2one('ir.ui.view')`,
so a `ref` from here would point at the wrong table and fail to load. Install
both for full coverage; each works without the other.

## Counter snippet

`s_nbet_capacity` figures animate from zero when scrolled into view. Set the
target on the element, not the text — the widget rewrites the text:

```xml
<span class="s_nbet_counter_value" data-target-value="13014" data-duration="2000">13,014</span>
```

`data-decimals` controls precision. The animation is skipped for visitors with
`prefers-reduced-motion`, and is disabled in the site builder so an
intermediate value can't be saved into the page.

> The MW figures shipped in `s_nbet_capacity` are placeholders. Replace them
> with current NBET market data before going live.
