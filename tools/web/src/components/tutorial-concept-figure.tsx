// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

type TutorialConceptItem = {
  label: string;
  detail: string;
};

export function TutorialConceptFigure({
  eyebrow,
  title,
  items,
  caption,
}: {
  eyebrow: string;
  title: string;
  items: readonly TutorialConceptItem[];
  caption: string;
}) {
  return (
    <figure className="tutorial-concept-figure">
      <div className="tutorial-concept-figure__heading">
        <span>{eyebrow}</span>
        <h3>{title}</h3>
      </div>
      <ol className="tutorial-concept-figure__items" role="list">
        {items.map((item, index) => (
          <li key={item.label}>
            <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{item.label}</strong>
              <p>{item.detail}</p>
            </div>
          </li>
        ))}
      </ol>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}
