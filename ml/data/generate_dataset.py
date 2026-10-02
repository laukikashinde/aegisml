"""
AegisML-Lite — Adult Income Dataset.

Uses a synthetic version of the UCI Adult Income dataset structure.
Target: income >50K (binary classification).

Features match the real Adult Income schema so drift injection
(covariate and concept) is realistic and interpretable.

Provides:
  - generate_splits()        → normal train/val/test
  - generate_drift_dataset() → covariate drift (F1)
  - generate_concept_drift_dataset() → concept drift (F2)
  - generate_bad_quality_dataset()   → data quality faults (F4)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

BASE_SEED = 42
DATA_DIR = Path(__file__).parent / "raw"

# ── Feature schema (Adult Income) ────────────────────────────────────────────

NUMERIC_FEATURES = [
    "age", "fnlwgt", "education_num", "capital_gain",
    "capital_loss", "hours_per_week",
]
CATEGORICAL_FEATURES = [
    "workclass", "education", "marital_status",
    "occupation", "relationship", "race", "sex", "native_country",
]
TARGET = "income_above_50k"
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _make_adult_income(
    n: int = 10_000,
    seed: int = BASE_SEED,
    drift_config: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Generate a synthetic Adult Income dataset.

    Distributions calibrated to match the real UCI Adult dataset statistics.
    drift_config controls covariate/concept/quality faults.
    """
    rng = np.random.default_rng(seed)
    dc = drift_config or {}

    # ── Numeric features ─────────────────────────────────────────────────────
    age = rng.normal(38.6, 13.6, n).clip(17, 90).round().astype(float)
    fnlwgt = rng.lognormal(11.2, 0.6, n).clip(10_000, 1_500_000).round()
    education_num = rng.normal(10.1, 2.6, n).clip(1, 16).round().astype(float)
    capital_gain = np.where(rng.random(n) < 0.08,
                            rng.lognormal(8.5, 1.5, n).clip(1, 100_000), 0.0)
    capital_loss = np.where(rng.random(n) < 0.05,
                            rng.lognormal(7.0, 1.0, n).clip(1, 5_000), 0.0)
    hours_per_week = rng.normal(40.4, 12.3, n).clip(1, 99).round().astype(float)

    # ── Categorical features ──────────────────────────────────────────────────
    workclass = rng.choice(
        ["Private", "Self-emp-not-inc", "Self-emp-inc", "Federal-gov",
         "Local-gov", "State-gov", "Without-pay", "Never-worked"],
        p=[0.690, 0.080, 0.035, 0.030, 0.065, 0.040, 0.045, 0.015],
        size=n,
    )
    education = rng.choice(
        ["Bachelors", "Some-college", "11th", "HS-grad", "Prof-school",
         "Assoc-acdm", "Assoc-voc", "9th", "7th-8th", "12th",
         "Masters", "1st-4th", "10th", "Doctorate", "5th-6th", "Preschool"],
        p=[0.165, 0.223, 0.036, 0.321, 0.018, 0.034, 0.042, 0.012,
           0.021, 0.013, 0.053, 0.006, 0.027, 0.013, 0.009, 0.007],
        size=n,
    )
    marital_status = rng.choice(
        ["Married-civ-spouse", "Divorced", "Never-married",
         "Separated", "Widowed", "Married-spouse-absent", "Married-AF-spouse"],
        p=[0.459, 0.135, 0.328, 0.034, 0.026, 0.015, 0.003],
        size=n,
    )
    occupation = rng.choice(
        ["Tech-support", "Craft-repair", "Other-service", "Sales",
         "Exec-managerial", "Prof-specialty", "Handlers-cleaners", "Machine-op-inspct",
         "Adm-clerical", "Farming-fishing", "Transport-moving", "Priv-house-serv",
         "Protective-serv", "Armed-Forces"],
        p=[0.030, 0.124, 0.118, 0.096, 0.099, 0.129, 0.040, 0.059,
           0.113, 0.031, 0.062, 0.035, 0.032, 0.032],
        size=n,
    )
    relationship = rng.choice(
        ["Wife", "Own-child", "Husband", "Not-in-family", "Other-relative", "Unmarried"],
        p=[0.103, 0.157, 0.404, 0.192, 0.032, 0.112],
        size=n,
    )
    race = rng.choice(
        ["White", "Asian-Pac-Islander", "Amer-Indian-Eskimo", "Other", "Black"],
        p=[0.855, 0.031, 0.009, 0.008, 0.097],
        size=n,
    )
    sex = rng.choice(["Male", "Female"], p=[0.669, 0.331], size=n)
    native_country = rng.choice(
        ["United-States", "Cuba", "Jamaica", "India", "Mexico", "South",
         "Japan", "Greece", "England", "Canada", "Germany", "Iran",
         "Philippines", "Italy", "Poland", "Columbia", "Cambodia", "Thailand",
         "Ecuador", "Laos", "Taiwan", "Haiti", "Portugal", "Dominican-Republic",
         "El-Salvador", "France", "Guatemala", "China", "Japan", "Yugoslavia",
         "Peru", "Outlying-US(Guam-USVI-etc)", "Scotland", "Trinadad&Tobago",
         "Greece", "Vietnam", "Hong", "Ireland", "Hungary", "Holand-Netherlands"],
        size=n,
    )

    # ── Apply drift configurations ────────────────────────────────────────────

    # F1 — Covariate drift: shift age and hours_per_week distributions
    if dc.get("covariate_age_shift"):
        age = (age + dc["covariate_age_shift"]).clip(17, 90)
    if dc.get("covariate_hours_scale"):
        hours_per_week = (hours_per_week * dc["covariate_hours_scale"]).clip(1, 99)
    if dc.get("covariate_education_shift"):
        education_num = (education_num + dc["covariate_education_shift"]).clip(1, 16)

    # F4 — Data quality: inject missing values
    if dc.get("missing_age_rate"):
        mask = rng.random(n) < dc["missing_age_rate"]
        age = age.astype(object)
        age[mask] = np.nan
    if dc.get("missing_occupation_rate"):
        mask = rng.random(n) < dc["missing_occupation_rate"]
        occupation = occupation.astype(object)
        occupation[mask] = np.nan
    # F4 — Range violations
    if dc.get("invalid_age_rate"):
        mask = rng.random(n) < dc["invalid_age_rate"]
        age_arr = np.array(age, dtype=object)
        age_arr[mask] = rng.choice([-5, -10, 200, 999], size=mask.sum())
        age = age_arr
    # F4 — Unknown categories
    if dc.get("unknown_workclass_rate"):
        mask = rng.random(n) < dc["unknown_workclass_rate"]
        wc = list(workclass)
        for i in np.where(mask)[0]:
            wc[i] = "UNKNOWN_CATEGORY"
        workclass = np.array(wc)

    # ── Target (income > 50K) ─────────────────────────────────────────────────
    # Logistic model calibrated to ~24% positive rate (matches real dataset)
    edu_num = pd.to_numeric(pd.Series(education_num), errors='coerce').fillna(10)
    age_num = pd.to_numeric(pd.Series(age), errors='coerce').fillna(38)
    hrs_num = pd.to_numeric(pd.Series(hours_per_week), errors='coerce').fillna(40)

    log_odds = (
        -7.4
        + 0.04  * age_num
        + 0.28  * edu_num
        + 0.02  * hrs_num
        + 0.8   * (np.array(sex) == "Male").astype(float)
        + 0.9   * (np.isin(np.array(marital_status),
                           ["Married-civ-spouse", "Married-AF-spouse"])).astype(float)
        + 1.2   * (np.isin(np.array(occupation),
                           ["Exec-managerial", "Prof-specialty"])).astype(float)
        + 0.0003 * pd.to_numeric(pd.Series(capital_gain), errors='coerce').fillna(0)
        + rng.normal(0, 0.8, n)
    )

    # F2 — Concept drift: flip/weaken the feature-target relationship
    if dc.get("concept_drift_education"):
        # Education correlation becomes weaker or reversed
        log_odds = log_odds - 0.5 * edu_num
    if dc.get("concept_drift_hours"):
        # Hours correlation reverses (overwork → not high income)
        log_odds = log_odds - 0.04 * hrs_num
    if dc.get("concept_drift_noise"):
        # Add significant noise to weaken all signals
        log_odds = log_odds + rng.normal(0, dc["concept_drift_noise"], n)

    prob = 1.0 / (1.0 + np.exp(-log_odds))
    income = (rng.random(n) < prob).astype(int)

    df = pd.DataFrame({
        "age": age,
        "workclass": workclass,
        "fnlwgt": fnlwgt,
        "education": education,
        "education_num": education_num,
        "marital_status": marital_status,
        "occupation": occupation,
        "relationship": relationship,
        "race": race,
        "sex": sex,
        "capital_gain": capital_gain,
        "capital_loss": capital_loss,
        "hours_per_week": hours_per_week,
        "native_country": native_country,
        TARGET: income,
    })
    return df


def generate_splits(
    output_dir: Path = DATA_DIR,
    n_samples: int = 10_000,
    seed: int = BASE_SEED,
    version: str = "v1",
    drift_config: Optional[dict] = None,
) -> dict[str, Path]:
    """Generate and save train/val/test splits. Returns file paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = _make_adult_income(n=n_samples, seed=seed, drift_config=drift_config)

    train_df, temp = train_test_split(
        df, test_size=0.30, stratify=df[TARGET], random_state=seed
    )
    val_df, test_df = train_test_split(
        temp, test_size=0.50, stratify=temp[TARGET], random_state=seed
    )

    paths = {}
    for name, split in [("train", train_df), ("val", val_df), ("test", test_df)]:
        p = output_dir / f"{name}_{version}.csv"
        split.to_csv(p, index=False)
        paths[name] = p
        print(f"  {name}: {len(split):,} rows → {p.name}")

    meta = {
        "version": version,
        "dataset": "adult_income",
        "n_samples": n_samples,
        "seed": seed,
        "target": TARGET,
        "features": ALL_FEATURES,
        "positive_rate": float(df[TARGET].mean()),
        "splits": {k: str(v) for k, v in paths.items()},
        "drift_config": drift_config or {},
    }
    (output_dir / f"metadata_{version}.json").write_text(json.dumps(meta, indent=2))
    print(f"  Positive rate: {df[TARGET].mean():.3f}")
    return paths


def generate_drift_dataset(
    output_dir: Path = DATA_DIR,
    version: str = "v2_covariate",
    drift_type: str = "covariate",
) -> dict[str, Path]:
    """Generate a drifted dataset for F1/F2/F4 simulations."""
    configs = {
        "covariate": {
            "covariate_age_shift": 8,
            "covariate_hours_scale": 1.3,
            "covariate_education_shift": 2,
        },
        "concept": {
            "concept_drift_education": True,
            "concept_drift_hours": True,
            "concept_drift_noise": 1.5,
        },
        "missing": {
            "missing_age_rate": 0.40,
            "missing_occupation_rate": 0.35,
        },
        "invalid": {
            "invalid_age_rate": 0.15,
            "unknown_workclass_rate": 0.20,
        },
    }
    dc = configs.get(drift_type, {})
    print(f"\nGenerating drifted dataset: type={drift_type}, version={version}")
    return generate_splits(
        output_dir=output_dir,
        n_samples=5_000,
        seed=BASE_SEED + 99,
        version=version,
        drift_config=dc,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v1")
    parser.add_argument("--n-samples", type=int, default=10_000)
    parser.add_argument("--drift-type", default=None,
                        choices=["covariate", "concept", "missing", "invalid"])
    args = parser.parse_args()

    print("=== AegisML-Lite — Adult Income Dataset Generator ===")
    if args.drift_type:
        v = f"v2_{args.drift_type}"
        generate_drift_dataset(version=v, drift_type=args.drift_type)
    else:
        generate_splits(n_samples=args.n_samples, version=args.version)
    print("\nDone.")
