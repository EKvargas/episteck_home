This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## F2b server integration

The Hub is mounted at `/app`. In local development, `HOME_HUB_DATA_MODE` defaults
to `MOCK`; mock mode never calls `fetch`. A production build or server requires
`HOME_HUB_DATA_MODE=LIVE` and fails closed otherwise. LIVE mode also requires the
trusted server-side `HOME_HUB_BFF_BASE_URL` origin, such as
`http://127.0.0.1:9933`; it is never sent to browser code. The server forwards
only the `episteck_home_session` cookie to that origin's `/bootstrap` endpoint.

The current prototype still renders existing mock domain panels. As a temporary
F2 compatibility seam, the existing local scope switcher uses an in-memory
default/selection for presentation, while its visible Person and Circle options,
viewer, and care relationship list come from the validated bootstrap. Care
relationships only classify the presentation label for a discovered Person;
they do not grant access. F3 owns the future `activeContext` state and persistence.

The Next.js proxy adds a nonce based CSP for `/app`, along with the current
security headers. Inline style attributes remain allowed because the existing
screens use React style props; script execution uses per request nonces.

F2b server boundary checks: `npm test`, `npm run lint`, `npx tsc --noEmit`, and
`npm run test:e2e`. The inactive Quadlet and the separate real-host pasta proof
are documented in [`deploy/home-hub/README.md`](../../deploy/home-hub/README.md).

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

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
