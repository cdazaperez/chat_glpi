'use client';

import { Chat } from '@/components';

export default function Home() {
  // Get GLPI base URL from environment for reference links
  // This should be configured via environment variables
  const glpiBaseUrl = process.env.NEXT_PUBLIC_GLPI_URL;

  return (
    <main className="h-screen">
      <Chat glpiBaseUrl={glpiBaseUrl} />
    </main>
  );
}
