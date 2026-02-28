"use client";

import React, { createContext, useContext, useMemo } from "react";
import { useSettingsContext } from "@/providers/SettingsProvider";
import {
  CHAT_BACKGROUND_NONE,
  CHAT_TEXT_COLOR_AUTO,
  CHAT_TEXT_DARK_MARKDOWN_CLASS,
  CHAT_TEXT_DARK_STATUS_CLASS,
  CHAT_TEXT_LIGHT_MARKDOWN_CLASS,
  CHAT_TEXT_LIGHT_STATUS_CLASS,
  getBackgroundById,
  ChatBackgroundOption,
} from "@/lib/constants/chatBackgrounds";

interface AppBackgroundContextType {
  /** The full background option object, or undefined if none/invalid */
  appBackground: ChatBackgroundOption | undefined;
  /** The URL of the background image, or null if no background is set */
  appBackgroundUrl: string | null;
  /** Whether a background is currently active */
  hasBackground: boolean;
  /** Optional markdown text color classes for assistant messages */
  messageTextClassName: string | null;
  /** Optional status text color class for assistant status text */
  statusTextClassName: string | null;
  /** Optional chat text mode class applied to the chat content area */
  chatTextModeClassName: string | null;
}

const AppBackgroundContext = createContext<
  AppBackgroundContextType | undefined
>(undefined);

export function AppBackgroundProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { settings } = useSettingsContext();

  const value = useMemo(() => {
    const chatBackgroundId = settings?.chat_background;
    const chatTextColor = settings?.chat_text_color ?? CHAT_TEXT_COLOR_AUTO;
    const appBackground = getBackgroundById(chatBackgroundId ?? null);
    const hasBackground =
      !!appBackground && appBackground.src !== CHAT_BACKGROUND_NONE;
    const appBackgroundUrl = hasBackground ? appBackground.src : null;

    let messageTextClassName: string | null = null;
    let statusTextClassName: string | null = null;
    let chatTextModeClassName: string | null = null;

    if (chatTextColor === "dark") {
      messageTextClassName = CHAT_TEXT_DARK_MARKDOWN_CLASS;
      statusTextClassName = CHAT_TEXT_DARK_STATUS_CLASS;
      chatTextModeClassName = null;
    } else if (chatTextColor === "light") {
      messageTextClassName = CHAT_TEXT_LIGHT_MARKDOWN_CLASS;
      statusTextClassName = CHAT_TEXT_LIGHT_STATUS_CLASS;
      chatTextModeClassName = "chat-text-light";
    } else if (hasBackground) {
      messageTextClassName = appBackground?.messageTextClassName ?? null;
      statusTextClassName = appBackground?.statusTextClassName ?? null;
      chatTextModeClassName =
        appBackground?.messageTextClassName === CHAT_TEXT_LIGHT_MARKDOWN_CLASS
          ? "chat-text-light"
          : null;
    }

    return {
      appBackground,
      appBackgroundUrl,
      hasBackground,
      messageTextClassName,
      statusTextClassName,
      chatTextModeClassName,
    };
  }, [settings?.chat_background, settings?.chat_text_color]);

  return (
    <AppBackgroundContext.Provider value={value}>
      {children}
    </AppBackgroundContext.Provider>
  );
}

export function useAppBackground() {
  const context = useContext(AppBackgroundContext);
  if (context === undefined) {
    throw new Error(
      "useAppBackground must be used within an AppBackgroundProvider"
    );
  }
  return context;
}
