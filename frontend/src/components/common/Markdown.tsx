import { memo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/cn'

const REMARK_PLUGINS = [remarkGfm]

const COMPONENTS: Components = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
}

interface MarkdownProps {
  children: string
  className?: string
  /** Show a blinking caret after the text (progressive streaming). */
  streaming?: boolean
}

/** GFM Markdown (tables!) for agent reports, chat answers and SKILL.md bodies. Raw HTML is not rendered. */
export const Markdown = memo(function Markdown({ children, className, streaming }: MarkdownProps) {
  return (
    <div className={cn('md', streaming && '[&>*:last-child]:caret', className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  )
})
