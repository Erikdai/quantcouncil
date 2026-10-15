/** Join class names, skipping falsy values. */
export function cn(...classes: Array<string | false | null | undefined | 0>): string {
  return classes.filter(Boolean).join(' ')
}
