import { LoaderCircle, Search } from "lucide-react";
import { useState, type FormEvent } from "react";

import type { Seed } from "../api/schemas";

export type DiscoveryControls = {
  prompt: string;
  adventure: "familiar" | "balanced" | "adventurous";
  allow_explicit: boolean;
  seed_ids: string[];
};

type Props = {
  seeds: Seed[];
  pending: boolean;
  onSubmit: (controls: DiscoveryControls) => void;
};

const adventureOptions = [
  { value: "familiar", label: "Familiar" },
  { value: "balanced", label: "Balanced" },
  { value: "adventurous", label: "Adventurous" },
] as const;

export function DiscoveryForm({ seeds, pending, onSubmit }: Props) {
  const [prompt, setPrompt] = useState("");
  const [adventure, setAdventure] = useState<DiscoveryControls["adventure"]>("balanced");
  const [allowExplicit, setAllowExplicit] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedPrompt = prompt.trim();
    if (normalizedPrompt.length < 2) {
      setError("Enter at least two characters.");
      return;
    }
    if (seeds.length === 0) {
      setError("Select at least one seed first.");
      return;
    }
    setError(null);
    onSubmit({
      prompt: normalizedPrompt,
      adventure,
      allow_explicit: allowExplicit,
      seed_ids: seeds.map((seed) => seed.id),
    });
  }

  return (
    <form className="discovery-form" onSubmit={submit} noValidate>
      <div className="field-group">
        <label htmlFor="discovery-prompt">Discovery prompt</label>
        <div className="prompt-control">
          <Search size={18} aria-hidden="true" />
          <input
            id="discovery-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            maxLength={500}
            placeholder="Late-night trip hop with colder textures"
            autoComplete="off"
            disabled={pending}
          />
        </div>
      </div>

      <fieldset className="control-fieldset">
        <legend>Adventure</legend>
        <div className="segmented-control">
          {adventureOptions.map((option) => (
            <label key={option.value}>
              <input
                type="radio"
                name="adventure"
                value={option.value}
                checked={adventure === option.value}
                onChange={() => setAdventure(option.value)}
                disabled={pending}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="toggle-row">
        <input
          type="checkbox"
          checked={allowExplicit}
          onChange={(event) => setAllowExplicit(event.target.checked)}
          disabled={pending}
        />
        <span className="toggle" aria-hidden="true" />
        <span>Allow explicit tracks</span>
      </label>

      {error ? <p className="form-error" role="alert">{error}</p> : null}

      <button className="primary-button" type="submit" disabled={pending}>
        {pending ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Search size={18} aria-hidden="true" />}
        {pending ? "Finding music" : "Find music"}
      </button>
    </form>
  );
}
