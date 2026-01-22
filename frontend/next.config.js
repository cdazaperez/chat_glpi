/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    NEXT_PUBLIC_APP_TITLE: process.env.NEXT_PUBLIC_APP_TITLE || 'Helpdesk AI',
    NEXT_PUBLIC_COMPANY_NAME: process.env.NEXT_PUBLIC_COMPANY_NAME || 'SkillNet',
  },
};

module.exports = nextConfig;
