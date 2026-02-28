// Default chat background images

export const CHAT_BACKGROUND_NONE = "none";

export const CHAT_TEXT_DARK_MARKDOWN_CLASS =
  "prose-p:text-text-dark-05 prose-li:text-text-dark-05 prose-strong:text-text-dark-05 prose-em:text-text-dark-05 prose-headings:text-text-dark-05";
export const CHAT_TEXT_DARK_STATUS_CLASS = "text-text-dark-03";
export const CHAT_TEXT_LIGHT_MARKDOWN_CLASS =
  "prose-p:text-text-light-05 prose-li:text-text-light-05 prose-strong:text-text-light-05 prose-em:text-text-light-05 prose-headings:text-text-light-05";
export const CHAT_TEXT_LIGHT_STATUS_CLASS = "text-text-light-03";

export const CHAT_TEXT_COLOR_AUTO = "auto";

export type ChatTextColorOptionId = "auto" | "dark" | "light";

export interface ChatTextColorOption {
  id: ChatTextColorOptionId;
  label: string;
  description: string;
}

export interface ChatBackgroundOption {
  id: string;
  src: string;
  thumbnail: string;
  label: string;
  // Optional markdown + status text styles when this background is active.
  messageTextClassName?: string;
  statusTextClassName?: string;
}

export const CHAT_TEXT_COLOR_OPTIONS: ChatTextColorOption[] = [
  {
    id: "auto",
    label: "Auto",
    description: "Automatically choose text color based on background.",
  },
  {
    id: "dark",
    label: "Dark Text",
    description: "Use darker text for brighter chat backgrounds.",
  },
  {
    id: "light",
    label: "Light Text",
    description: "Use lighter text for darker chat backgrounds.",
  },
];

// Curated collection of scenic backgrounds that work well as chat backgrounds
export const CHAT_BACKGROUND_OPTIONS: ChatBackgroundOption[] = [
  {
    id: "none",
    src: CHAT_BACKGROUND_NONE,
    thumbnail: CHAT_BACKGROUND_NONE,
    label: "None",
  },
  {
    id: "clouds",
    src: "/chat-backgrounds/clouds.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/clouds.jpg",
    label: "Clouds",
    messageTextClassName: CHAT_TEXT_DARK_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_DARK_STATUS_CLASS,
  },
  {
    id: "hills",
    src: "/chat-backgrounds/hills.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/hills.jpg",
    label: "Hills",
    messageTextClassName: CHAT_TEXT_DARK_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_DARK_STATUS_CLASS,
  },
  {
    id: "plant",
    src: "/chat-backgrounds/plant.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/plant.jpg",
    label: "Plants",
    messageTextClassName: CHAT_TEXT_DARK_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_DARK_STATUS_CLASS,
  },
  {
    id: "plants2",
    src: "/chat-backgrounds/Plants2.jpeg",
    thumbnail: "/chat-backgrounds/thumbnails/plants2.jpg",
    label: "Plants 2",
    messageTextClassName: CHAT_TEXT_DARK_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_DARK_STATUS_CLASS,
  },
  {
    id: "plants3",
    src: "/chat-backgrounds/plants3.jpeg",
    thumbnail: "/chat-backgrounds/thumbnails/plants3.jpg",
    label: "Plants 3",
    messageTextClassName: CHAT_TEXT_DARK_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_DARK_STATUS_CLASS,
  },
  {
    id: "waterfall",
    src: "/chat-backgrounds/Waterfall.jpeg?v=20260220-2",
    thumbnail: "/chat-backgrounds/thumbnails/waterfall.jpg?v=20260220-2",
    label: "Waterfall",
    messageTextClassName: CHAT_TEXT_DARK_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_DARK_STATUS_CLASS,
  },
  {
    id: "mountains",
    src: "/chat-backgrounds/mountains.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/mountains.jpg",
    label: "Mountains",
    messageTextClassName: CHAT_TEXT_LIGHT_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_LIGHT_STATUS_CLASS,
  },
  {
    id: "night",
    src: "/chat-backgrounds/night.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/night.jpg",
    label: "Night",
    messageTextClassName: CHAT_TEXT_LIGHT_MARKDOWN_CLASS,
    statusTextClassName: CHAT_TEXT_LIGHT_STATUS_CLASS,
  },
];

export const getBackgroundById = (
  id: string | null
): ChatBackgroundOption | undefined => {
  if (!id || id === CHAT_BACKGROUND_NONE) {
    return CHAT_BACKGROUND_OPTIONS[0];
  }
  return CHAT_BACKGROUND_OPTIONS.find((bg) => bg.id === id);
};
