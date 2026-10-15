interface LogoProps {
  className?: string;
}

export function Logo({ className }: LogoProps) {
  return (
    <svg
      className={className}
      width="40"
      height="40"
      viewBox="0 0 40 40"
      role="img"
      aria-label="AI Incident Investigator"
    >
      <path d="M8 10 20 25 32 10" fill="none" stroke="#9aa9bc" strokeWidth="2" />
      <circle cx="8" cy="10" r="4" fill="#182536" />
      <circle cx="32" cy="10" r="4" fill="#182536" />
      <circle cx="20" cy="25" r="8" fill="white" stroke="#2764e7" strokeWidth="2" />
      <circle cx="20" cy="25" r="3.5" fill="#2764e7" />
    </svg>
  );
}
