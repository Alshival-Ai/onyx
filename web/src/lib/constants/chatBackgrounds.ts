// Default chat background images

export const CHAT_BACKGROUND_NONE = "none";

export interface ChatBackgroundOption {
  id: string;
  src: string;
  thumbnail: string;
  label: string;
}

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
  },
  {
    id: "hills",
    src: "/chat-backgrounds/hills.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/hills.jpg",
    label: "Hills",
  },
  {
    id: "plant",
    src: "/chat-backgrounds/plant.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/plant.jpg",
    label: "Plants",
  },
  {
    id: "plants2",
    src: "/chat-backgrounds/Plants2.jpeg",
    thumbnail: "/chat-backgrounds/thumbnails/plants2.jpg",
    label: "Plants 2",
  },
  {
    id: "plants3",
    src: "/chat-backgrounds/plants3.jpeg",
    thumbnail: "/chat-backgrounds/thumbnails/plants3.jpg",
    label: "Plants 3",
  },
  {
    id: "waterfall",
    src: "/chat-backgrounds/Waterfall.jpeg?v=20260220-2",
    thumbnail: "/chat-backgrounds/thumbnails/waterfall.jpg?v=20260220-2",
    label: "Waterfall",
  },
  {
    id: "mountains",
    src: "/chat-backgrounds/mountains.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/mountains.jpg",
    label: "Mountains",
  },
  {
    id: "night",
    src: "/chat-backgrounds/night.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/night.jpg",
    label: "Night",
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
