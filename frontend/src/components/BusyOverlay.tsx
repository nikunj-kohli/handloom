interface Props {
  label: string;
  step: number;
  steps: string[];
  hint?: string;
}

export default function BusyOverlay({ label, step, steps, hint }: Props) {
  return (
    <div className="overlay" role="status" aria-live="polite">
      <div className="overlay-card">
        <div className="spinner" aria-hidden="true" />
        <h2>{label}</h2>
        <ol className="overlay-steps">
          {steps.map((item, index) => (
            <li
              key={item}
              className={index < step ? "done" : index === step ? "active" : "todo"}
            >
              <span className="overlay-dot" aria-hidden="true" />
              {item}
            </li>
          ))}
        </ol>
        <p className="overlay-hint">{hint ?? "No sign-in, no setup. This usually takes a few seconds."}</p>
      </div>
    </div>
  );
}
