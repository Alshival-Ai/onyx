"use client";

import Button from "@/refresh-components/buttons/Button";
import { AuthType, NEXT_PUBLIC_OIDC_LOGIN_PROVIDER } from "@/lib/constants";
import { FcGoogle } from "react-icons/fc";
import type { IconProps } from "@opal/types";

interface SignInButtonProps {
  authorizeUrl: string;
  authType: AuthType;
}

export default function SignInButton({
  authorizeUrl,
  authType,
}: SignInButtonProps) {
  let button: React.ReactNode;
  let icon: React.FunctionComponent<IconProps> | undefined;

  if (authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD) {
    button = "Continue with Google";
    icon = FcGoogle;
  } else if (authType === AuthType.OIDC) {
    button = "Continue with OIDC SSO";
  } else if (authType === AuthType.SAML) {
    button = "Continue with SAML SSO";
  }

  const url = new URL(authorizeUrl);
  const finalAuthorizeUrl = url.toString();

  if (!button) {
    throw new Error(`Unhandled authType: ${authType}`);
  }

  const handleOidcClick = async () => {
    try {
      const res = await fetch(finalAuthorizeUrl, { credentials: "include" });
      if (!res.ok) {
        throw new Error(`OIDC authorize failed: ${res.status}`);
      }
      const data = (await res.json()) as { authorization_url?: string };
      if (data.authorization_url) {
        window.location.href = data.authorization_url;
        return;
      }
    } catch (err) {
      console.error("OIDC authorize fetch failed, falling back to direct URL", err);
    }
    window.location.href = finalAuthorizeUrl;
  };

  if (authType === AuthType.OIDC) {
    if (NEXT_PUBLIC_OIDC_LOGIN_PROVIDER?.toLowerCase() === "microsoft") {
      return (
        <button
          type="button"
          className="w-full flex justify-center"
          aria-label="Sign in with Microsoft"
          onClick={handleOidcClick}
        >
          <img
            src="/ms-sign-in-light.svg"
            alt="Sign in with Microsoft"
            className="block dark:hidden h-10 w-full max-w-[320px]"
          />
          <img
            src="/ms-sign-in-dark.svg"
            alt="Sign in with Microsoft"
            className="hidden dark:block h-10 w-full max-w-[320px]"
          />
        </button>
      );
    }

    // Use a button to avoid Next.js prefetch/XHR which breaks OIDC redirects.
    return (
      <button
        type="button"
        className="p-2 h-fit rounded-12 w-full flex flex-row items-center justify-center gap-1.5 button-main-primary"
        onClick={handleOidcClick}
      >
        <span className="button-main-primary-text">Continue with OIDC SSO</span>
      </button>
    );
  }

  return (
    <Button
      secondary={
        authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD
      }
      className="!w-full"
      leftIcon={icon}
      href={finalAuthorizeUrl}
    >
      {button}
    </Button>
  );
}
