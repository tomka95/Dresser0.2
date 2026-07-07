/* §5 · Stylist chat — componentized from the ~1075-line /chat monolith. */
export { ChatHeader } from './ChatHeader';
export { IncognitoBanner } from './IncognitoBanner';
export { MessageList } from './MessageList';
export { ChatMessage } from './ChatMessage';
export { OutfitCard, OutfitStrip } from './OutfitCard';
export { OutfitActions } from './OutfitActions';
export { Composer } from './Composer';
export { QuickPrompts } from './QuickPrompts';
export { HistorySheet } from './HistorySheet';
export { EmptyGreeting } from './EmptyGreeting';
export type { ChatMessage as ChatMessageModel, ClosetItemLite, PendingImage } from './types';
export { timeAgo } from './types';
