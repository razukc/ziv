# Feel-tool hosting

- Site: `ziv-feel-tool`
- Site ID: `4fc79a54-fb2c-447a-b589-73e1d0c86273`
- Canonical environment: `production` (published)
- Public URL: <https://site-5505fea77ec84b4f8e1a5d70c82d5877.freebuff.page>
- Preview: still published in the Sites panel; production above is canonical.

The page source is [`docs/haptic-name-marks.html`](../../docs/haptic-name-marks.html).
Before deploying, copy it to `public/index.html`:

```bash
cp docs/haptic-name-marks.html sites/feel-tool/public/index.html
```

Then deploy with `sites/feel-tool/deploy.json` to the `production`
environment. The page is public; no auth or storage bindings are used.
Deploying does not publish an unpublished environment: use
`sites_set_published(..., published=true)` once, and afterward a deploy to the
published production environment replaces the live code.
