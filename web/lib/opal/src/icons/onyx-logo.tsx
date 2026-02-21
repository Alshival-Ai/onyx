import type { IconProps } from "@opal/types";

const SvgOnyxLogo = ({ size = 24, className, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 56 56"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M28 0l8.5 17.5L56 20l-14 13.5L45.5 56 28 46l-17.5 10L14 33.5 0 20l19.5-2.5L28 0z"
      fill="currentColor"
    />
    <path
      d="M28 12l4.5 9.5L43 23l-7.5 7L37 41l-9-5-9 5 1.5-11L13 23l10.5-1.5L28 12z"
      fill="currentColor"
      fillOpacity="0.3"
    />
  </svg>
);

export default SvgOnyxLogo;
