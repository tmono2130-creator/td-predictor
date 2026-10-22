This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.


## Weekly data pipeline

The web app reads `public/data/manifest.json` to discover published season/week snapshots. The exporter writes each week to its own folder:

```text
public/data/
  manifest.json
  seasons/2026/week-7/<snapshot-id>/board.json
  seasons/2026/week-7/<snapshot-id>/breakdowns.json
  seasons/2026/week-8/<snapshot-id>/board.json
  seasons/2026/week-8/<snapshot-id>/breakdowns.json
```

From the Python model directory, export into this site's `public/data` directory (adjust the relative path for your checkout):

```bash
python export_json.py --season 2026 --week 7 --out ../td-predictor-web/public/data
python export_json.py --season 2026 --week 8 --out ../td-predictor-web/public/data
```

The exporter builds a complete, uniquely named snapshot in a staging directory and validates the board and breakdown metadata before publishing the manifest. The manifest is updated last and points at immutable snapshot files, so if a model/data step fails, the previous published snapshot remains intact. `--skip-breakdowns` publishes a board-only update and preserves an already-published breakdown link for that week. The site intentionally does not fall back to the checked-in placeholder `board.json` if the manifest is missing.

Run the export-contract regression tests from the repository root:

```bash
python -m unittest tests.test_weekly_export
```

After exporting, commit/deploy the generated `public/data/manifest.json` and `public/data/seasons/` files with the web app so the static host serves the selected week's real model output.
