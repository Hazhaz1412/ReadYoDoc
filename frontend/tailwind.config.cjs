/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{html,js,svelte}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#06101e',
          900: '#091427',
          850: '#0d1d35',
          800: '#112544',
          700: '#18345e',
        },
        sky: {
          300: '#89d8ff',
          400: '#64d2ff',
          500: '#3ca7ff',
        },
        amber: {
          300: '#ffd595',
          400: '#ffba66',
        },
      },
      fontFamily: {
        sans: ['Manrope', 'sans-serif'],
        mono: ['IBM Plex Mono', 'monospace'],
      },
      boxShadow: {
        glow: '0 24px 80px rgba(3, 8, 18, 0.48)',
        soft: '0 12px 36px rgba(3, 8, 18, 0.32)',
      },
      backgroundImage: {
        'hero-grid':
          'radial-gradient(circle at top left, rgba(101, 210, 255, 0.16), transparent 30%), radial-gradient(circle at 80% 20%, rgba(255, 186, 102, 0.12), transparent 22%)',
      },
      keyframes: {
        rise: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '.45' },
        },
      },
      animation: {
        rise: 'rise 240ms ease-out',
        'pulse-soft': 'pulseSoft 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
