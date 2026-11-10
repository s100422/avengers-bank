type SpiderMascotProps = {
  className?: string;
  label?: string;
};

export function SpiderMascot({ className = "", label }: SpiderMascotProps) {
  return (
    <svg
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={`block ${className}`}
      fill="none"
      focusable="false"
      role={label ? "img" : undefined}
      viewBox="0 0 100 100"
    >
      <path d="M50 2v24" stroke="#302625" strokeLinecap="round" strokeWidth="2.5" />
      <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="5.5">
        <path d="M34 37 25 29q-5-4-10-1l-5 3M28 46 18 41q-5-2-8 2l-2 6M27 57 17 58q-5 1-7 5l-2 4M35 66 28 73q-3 4-2 8" />
        <path d="M66 37 75 29q5-4 10-1l5 3M72 46 82 41q5-2 8 2l2 6M73 57 83 58q5 1 7 5l2 4M65 66 72 73q3 4 2 8" />
      </g>
      <circle cx="50" cy="51" r="24" fill="currentColor" />
      <circle cx="41.5" cy="51" r="8" fill="#FFF8F4" />
      <circle cx="58.5" cy="51" r="8" fill="#FFF8F4" />
      <circle cx="43.5" cy="53" r="2.4" fill="#302625" />
      <circle cx="56.5" cy="53" r="2.4" fill="#302625" />
      <circle cx="35.5" cy="62" r="3" fill="#FDE3D7" />
      <circle cx="64.5" cy="62" r="3" fill="#FDE3D7" />
      <path d="M45 63q5 6 10 0" stroke="#302625" strokeLinecap="round" strokeWidth="2.5" />
    </svg>
  );
}
