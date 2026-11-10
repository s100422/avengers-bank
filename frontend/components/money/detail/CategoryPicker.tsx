import { CATEGORY_LABELS, type Category } from "@/lib/money";

// 사용자가 고를 수 있는 분류 (미분류는 고르는 값이 아니다)
export const PICKABLE = (Object.keys(CATEGORY_LABELS) as Category[]).filter((c) => c !== "UNCLASSIFIED");

/** 분류 고르기: 라디오 버튼 묶음 */
export function CategoryPicker({ value, onChange, legend = "분류" }: { value: Category | null; onChange: (c: Category) => void; legend?: string }) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm text-slate">{legend}</legend>
      <div className="grid grid-cols-3 gap-2">
        {PICKABLE.map((c) => (
          <label
            key={c}
            className={`flex min-h-11 cursor-pointer items-center justify-center rounded-xl border px-2 text-center text-sm has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-coral/40 ${
              value === c ? "border-coral bg-coral-soft font-semibold text-coral" : "border-line"
            }`}
          >
            <input type="radio" name="category" value={c} checked={value === c} onChange={() => onChange(c)} className="sr-only" />
            {CATEGORY_LABELS[c]}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
