# Suppliers, stock and cost

`PROJECT.md` records the user's country, currency and the suppliers they buy from. Ask in stage 1 if it is missing. Do not assume a supplier ships to the user's country.

## What can be checked automatically

- **LCSC**: look up each part number on lcsc.com through a browser tool (`https://www.lcsc.com/search?q=<part number>`). If the site rate-limits or shows a verification page, wait and retry later; never work around it. Record own stock, partner stock as a separate number, price at the build quantity, and the supplier number.
- **Everything else is checked by the user by hand.** DigiKey, Mouser and most regional distributors block automated browsing. Do not try to get around that.

## Hand-check flow (stage 7)

For every line that LCSC does not stock, or stocks too few of:
1. Write `reports/07-hand-check.md`: one row per line with refs, MPN, quantity needed, and a search link for each supplier in `PROJECT.md`. Leave columns for stock, unit price, currency and date.
2. Ask the user to open the links and type the numbers back, or to fill in the file. In guided mode, explain what to look for: the exact part number including suffix, stock at that supplier's own warehouse, lifecycle status, minimum order quantity.
3. Copy the user's numbers into `07-bom.md`, marked "checked by user" with the date. A line the user did not check stays open.
4. Never fill in a number the user did not give.

## Regional availability and cost

- Report prices in the currency of `PROJECT.md`. Keep the supplier's own currency next to it and state the exchange rate and its date if you convert; ask the user for the rate rather than guessing.
- Landed cost (shipping, import duty, tax) differs by country and by order. Do not estimate duty or tax rates. Give the parts subtotal per supplier, and list shipping, duty and tax as "to be added by the user".
- Prefer fewer suppliers: a part that costs a little more at a supplier already in the order is usually cheaper than a second shipment. Say so and let the user decide.
- **India (first supported region).** Ask the user which of these they use and record it; the list is a starting point, not a recommendation, and none of them is checked automatically: LCSC (ships internationally), DigiKey India, Mouser India, element14 India, and local stockists such as Robu.in and Evelta. Local stockists carry common parts and modules but rarely the exact part numbers of a power design; expect to split the order.
- Other regions: same flow with the suppliers the user names.

Stock and prices are a snapshot. Write the date in the report.
