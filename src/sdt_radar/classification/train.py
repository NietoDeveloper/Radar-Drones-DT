"""``python -m sdt_radar.classification.train`` — retrain and save the packaged synthetic model."""

from __future__ import annotations

from .model import DEFAULT_MODEL, train_default


def main() -> None:
    model, metrics = train_default()
    model.save(DEFAULT_MODEL)
    print(f"saved {DEFAULT_MODEL}")
    for k, v in metrics.items():
        print(f"  {k}: {v:.3f}")


if __name__ == "__main__":
    main()
