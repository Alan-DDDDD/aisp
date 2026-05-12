/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f5f7ff',
          100: '#e5eaff',
          500: '#5b6cff',
          600: '#4754e6',
          700: '#3340b8',
        },
      },
    },
  },
  plugins: [],
}
