import { useMDXComponents as getThemeComponents } from 'nextra-theme-docs'

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || ''

// Get the default MDX components from nextra-theme-docs
const themeComponents = getThemeComponents()

// Custom img component that prepends basePath to absolute paths
function Img({ src, alt, ...props }) {
  const resolvedSrc = src?.startsWith('/') ? `${basePath}${src}` : src
  return (
    <img
      src={resolvedSrc}
      alt={alt}
      className="w-full max-w-5xl mx-auto"
      {...props}
    />
  )
}

export function useMDXComponents(components) {
  return {
    ...themeComponents,
    img: Img,
    ...components
  }
}
