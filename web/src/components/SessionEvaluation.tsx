import { useMutation } from "@tanstack/react-query";
import { Check, LoaderCircle } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, ApiError } from "../api/client";

const comparisons = [
  { value: "better", label: "Better" },
  { value: "same", label: "About the same" },
  { value: "worse", label: "Worse" },
  { value: "not_sure", label: "Not sure" },
] as const;

type Comparison = (typeof comparisons)[number]["value"];

export function SessionEvaluation({ sessionId }: { sessionId: string }) {
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [usefulness, setUsefulness] = useState("3");
  const [novelty, setNovelty] = useState("3");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => api.saveEvaluation(sessionId, {
      comparison: comparison!,
      explanation_usefulness: ratingValue(usefulness),
      novelty_quality: ratingValue(novelty),
      comment: comment.trim() || null,
    }),
    onError: (reason) => setError(reason instanceof ApiError ? reason.message : "Evaluation could not be saved."),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!comparison) {
      setError("Choose a comparison first.");
      return;
    }
    setError(null);
    mutation.mutate();
  }

  if (mutation.isSuccess) {
    return <div className="evaluation-saved" role="status"><Check size={18} aria-hidden="true" /><span>Evaluation saved</span></div>;
  }

  return (
    <section className="evaluation-section" aria-labelledby="evaluation-heading">
      <div className="section-heading"><div><p className="eyebrow">Beta evaluation</p><h2 id="evaluation-heading">How did this session compare?</h2></div></div>
      <form className="evaluation-form" onSubmit={submit}>
        <fieldset className="control-fieldset">
          <legend>Compared with Spotify recommendations</legend>
          <div className="segmented-control comparison-control">
            {comparisons.map((option) => <label key={option.value}><input type="radio" name="comparison" value={option.value} checked={comparison === option.value} onChange={() => setComparison(option.value)} /><span>{option.label}</span></label>)}
          </div>
        </fieldset>
        <div className="rating-grid">
          <label>Explanation usefulness<input aria-label="Explanation usefulness" type="number" min={1} max={5} value={usefulness} onChange={(event) => setUsefulness(event.target.value)} /></label>
          <label>Novelty quality<input aria-label="Novelty quality" type="number" min={1} max={5} value={novelty} onChange={(event) => setNovelty(event.target.value)} /></label>
        </div>
        <div className="field-group"><label htmlFor={`evaluation-comment-${sessionId}`}>Optional comment</label><textarea id={`evaluation-comment-${sessionId}`} value={comment} maxLength={1000} rows={3} onChange={(event) => setComment(event.target.value)} /></div>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="secondary-button" type="submit" disabled={mutation.isPending}>{mutation.isPending ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : <Check size={17} aria-hidden="true" />} Save evaluation</button>
      </form>
    </section>
  );
}

function ratingValue(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.min(5, Math.max(1, Math.round(parsed)));
}
