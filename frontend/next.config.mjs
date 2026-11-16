/** @type {import('next').NextConfig} */
const isProd = process.env.NODE_ENV === 'production';

const nextConfig = {
  output: 'export',
  images: {
    unoptimized: true,
  },
  env: {
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://gvmgoqsinfvuwezszmjd.supabase.co',
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd2bWdvcXNpbmZ2dXdlenN6bWpkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTMxOTQ0NTEsImV4cCI6MjEwODc3MDQ1MX0.fTjCup-vjlk3Y7ZAWmNsBGz05YfysQrClzQJJ8IJb1A',
  },
  ...(isProd
    ? {}
    : {
        async rewrites() {
          return [
            {
              source: '/api/:path*',
              destination: 'http://127.0.0.1:8000/api/:path*',
            },
          ];
        },
      }),
};

export default nextConfig;
