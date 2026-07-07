/* §0 chrome — materials, marks, buttons, surfaces, states, toasts, loaders. */
export { M, NAV_CLEAR } from './materials';
export { StylistMark } from './StylistMark';
export { Spark } from './Spark';
export {
  Btn,
  RoundBtn,
  DSButton,
  PendingDots,
  type BtnProps,
  type BtnVariant,
  type BtnSize,
  type RoundBtnProps,
} from './Button';
export { Field, type FieldProps } from './Field';
export { DialogFrame, type DialogFrameProps, type DialogTone } from './DialogFrame';
export {
  Medallion,
  StateBlock,
  StateScreen,
  ErrorState,
  OfflineBanner,
  OfflineScreen,
  PermissionState,
  RateLimitState,
  NotFoundState,
  CrashScreen,
  SuccessPop,
  type MedallionProps,
  type MedallionTone,
  type StateBlockProps,
  type PermissionKind,
} from './StateBlock';
export { Toast, ToastHost } from './Toast';
export { useToastStore, type ToastTone, type ToastItem, type ToastInput, type ToastAction } from '@/stores/useToastStore';
export {
  LottieMark,
  Mark,
  Thinking,
  Sk,
  SkCircle,
  SkTile,
  SkGrid,
  SkList,
  SkDetail,
  SkChat,
  SkFeed,
  TypingDots,
  ProcessingPill,
  DeckLoading,
  ImageFill,
  Splash,
  ThinkingScreen,
  type LottieMarkProps,
  type SkProps,
  type ProcessingPillProps,
  type ProcessingState,
} from './loaders';

/* Pre-redesign design-system pieces (still consumed by existing screens). */
export { Icon, type IconName } from './Icon';
export { GlassCard } from './GlassCard';
export { DSBadge } from './Badge';
export { DSSearchBar } from './SearchBar';
export { CategoryChips, type CategoryChipItem } from './CategoryChips';
export { DSSwitch } from './Switch';
export { DSAvatar } from './Avatar';
export { SectionHeader } from './SectionHeader';
export { ContextMenu, type ContextMenuItem } from './ContextMenu';
export { ItemTile } from './ItemTile';
export { Sheet, RadioRow } from './Sheet';
export { FormField } from './FormField';
export { GmailGlyph } from './GmailGlyph';
export { HangerImg } from './HangerImg';
export { TopBar } from './TopBar';
