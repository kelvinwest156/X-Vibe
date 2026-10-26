/** @type {import('next').NextConfig} */
const isProdBuild = process.env.NODE_ENV === 'production';

const nextConfig = {
  ...(isProdBuild ? { output: 'export' } : {}),
  images: {
    unoptimized: true,
  },
  async rewrites() {
    if (isProdBuild) return [];
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*',
      },
    ];
  },
};

export default nextConfig;
