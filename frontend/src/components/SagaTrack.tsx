import { formatPreciseTime } from "../lib/format";
import type { SagaStep, StepState } from "../lib/saga";
import { Icon } from "./ui/Icon";

const STATE_LABELS: Record<StepState, string> = {
  complete: "Completed",
  active: "In progress",
  retrying: "Retrying",
  waiting: "Waiting",
  failed: "Failed",
  skipped: "Not reached",
};

function Marker({ state, index }: { state: StepState; index: number }) {
  if (state === "complete") return <Icon name="check" size={14} />;
  if (state === "failed") return <Icon name="close" size={14} />;
  if (state === "retrying") return <Icon name="replay" size={13} />;
  return <span>{index + 1}</span>;
}

export function SagaTrack({ steps }: { steps: SagaStep[] }) {
  return (
    <ol className="saga" aria-label="Saga progress">
      {steps.map((step, index) => (
        <li key={step.key} className={`saga__step saga__step--${step.state}`}>
          <div className="saga__marker" aria-hidden="true">
            <Marker state={step.state} index={index} />
          </div>
          <div className="saga__text">
            <div className="saga__label">
              {step.label}
              <span className="visually-hidden">: {STATE_LABELS[step.state]}</span>
            </div>
            <div className="saga__service mono">{step.service}</div>
            <div className="saga__meta">
              {step.at ? (
                <time dateTime={step.at}>{formatPreciseTime(step.at)}</time>
              ) : (
                <span className="saga__state">{STATE_LABELS[step.state]}</span>
              )}
            </div>
            {step.note && <div className="saga__note">{step.note}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}