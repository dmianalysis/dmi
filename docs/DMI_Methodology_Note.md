# Distributional Misery Index: Methodology Note

**Original version:** 0.1.9 (December 2024). **Current release:** v0.1.12
(August 2026). **Author:** Thomas C. Williams.

> ## ⚠️ v0.1.12 STATUS BANNER — READ FIRST
>
> This document was drafted for **v0.1.9** and is preserved here as the
> most detailed technical description of the DMI construction. Several of
> its specific claims are **superseded or withdrawn** under **v0.1.12**,
> which is a pre-1.0 exceptional breaking public-schema release.
>
> **Superseded / withdrawn under v0.1.12:**
>
> 1. **Core CPI alternative** — withdrawn. The code that produced
>    `dmi_release_*_core.json` in earlier releases derived its inputs
>    from headline CPI and did not implement a bona fide core-inflation
>    calculation. See
>    [`docs/repair/CORE_WITHDRAWAL.md`](repair/CORE_WITHDRAWAL.md).
>    v0.1.12 publishes only **Baseline** (U-3, headline CPI) and
>    **Slack-Plus** (U-6, headline CPI) as operational specifications.
> 2. **Bootstrap confidence intervals** (§3.6, §5.4, elsewhere) — not
>    part of the v0.1.12 published contract. `dmi_release_*_with_ci.json`
>    files that predate v0.1.12 are historical artifacts.
> 3. **2011-2024 historical time series** (§7, Appendix B backfill
>    recipes) — not re-validated under v0.1.12. Baseline coverage in
>    the v0.1.12 published manifest starts at 2025-12; Slack-Plus
>    coverage starts at 2026-03. Any long-run time-series claim in §7,
>    and any command in Appendix B that emits
>    `dmi_timeseries_2010_2024.json`, has NOT been carried forward.
>    The current public timeseries lives at
>    `data/outputs/published/dmi_timeseries.json` and is Baseline-only.
> 4. **Specific point estimates and CI widths for November 2024**
>    (Executive Summary, §5, §7) — pre-v0.1.12 numbers, retained for
>    historical context only.
>
> For the current v0.1.12 published contract, consult:
>
> - [`README.md`](../README.md) — top-level v0.1.12 statement
> - [`docs/API.md`](API.md) — current data-access reference
> - [`docs/Alternative_Specifications.md`](Alternative_Specifications.md) —
>   current Baseline + Slack-Plus discussion
> - [`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](repair/V0.1.12_ALIGNMENT_AUDIT.md) —
>   audit backing the v0.1.12 repair
>
> The formula, the group-weighted-inflation construction, the U-3 slack
> integration, and the CE-weight methodology in the body of this note
> are **still current** under v0.1.12.

---

## Executive Summary

The **Distributional Misery Index (DMI)** measures economic pressure across income groups by combining inflation and unemployment with income-specific expenditure patterns. Unlike the traditional Misery Index, which treats all households identically, DMI recognizes that economic shocks affect different income groups differently.

**Key Findings (November 2024)**:
- Q1 (lowest income) DMI: 6.88 [6.83, 6.94]
- Q5 (highest income) DMI: 6.65 [6.59, 6.71]
- Inflation ranges from 2.68% (Q1) to 2.45% (Q5)
- Unemployment: 4.2% (national, all groups)

**Methodology in One Sentence**: DMI combines group-specific inflation (weighted by Consumer Expenditure patterns) with national unemployment using the formula: DMI = 2.0 × (0.5 × Inflation + 0.5 × Unemployment).

**Use Cases**: Research on distributional inflation, policy analysis of economic pressure, public communication of economic conditions, media reporting on household financial stress.

---

## 1. Introduction

### 1.1 Motivation

Economic policy debates often focus on aggregate statistics—headline inflation (CPI-U), the unemployment rate (U-3), GDP growth—that mask substantial heterogeneity across the income distribution. A 3% inflation rate means something very different to a household spending 30% of its budget on food versus 10%. Similarly, a 4% unemployment rate provides cold comfort to workers in sectors experiencing higher joblessness.

The traditional **Misery Index**, popularized in the 1970s, sums inflation and unemployment to create a single measure of economic distress:

```
Misery Index = Inflation + Unemployment
```

While simple and intuitive, this index has critical limitations:
1. **No distributional perspective**: Treats all households as experiencing the same inflation
2. **Equal weights**: Assumes inflation and unemployment matter equally (questionable)
3. **No expenditure patterns**: Ignores that poor households spend more on necessities

The **Distributional Misery Index (DMI)** addresses these limitations by:
- Computing **group-specific inflation** using income quintile expenditure patterns
- Allowing **flexible weighting** of inflation vs unemployment
- Providing **95% confidence intervals** to quantify statistical uncertainty
- Supporting **alternative specifications** (U-6, Core CPI) for sensitivity analysis

### 1.2 Research Context

DMI builds on extensive literature:
- **Distributional inflation**: Hobijn & Lagakos (2005), Argente & Lee (2020)
- **Consumer expenditure heterogeneity**: Aguiar & Bils (2015)
- **Economic distress measurement**: Case & Deaton (2020) "Deaths of Despair"

### 1.3 Public Communication Value

For non-economists, DMI answers the question: **"How much economic pressure are different income groups experiencing right now?"**

A DMI of 6.88 (Q1, Nov 2024) means:
- Below historical average (2011-2024 mean: 9.73)
- At 15th percentile (only 15% of historical periods had lower DMI)
- Trending downward (from 2020 COVID peak of ~13)

---

## 2. Theoretical Framework

### 2.1 Economic Pressure Components

**Inflation** erodes purchasing power. A household with fixed nominal income experiences declining real consumption as prices rise. The impact varies by expenditure patterns—households spending more on rapidly inflating categories feel more pressure.

**Unemployment** reduces income directly (for job losers) and creates income uncertainty (for workers fearing layoffs). Even employed workers may curtail spending due to precautionary savings motives when unemployment is high.

Together, inflation and unemployment capture the two primary sources of economic stress for households:
1. **Price pressure**: How much does my dollar buy?
2. **Income pressure**: Can I keep my job?

### 2.2 Why Income Groups Differ

**Expenditure Patterns**: Lower-income households devote larger budget shares to necessities (food, housing, transportation) which may inflate faster than discretionary goods (recreation, apparel). The Bureau of Labor Statistics Consumer Expenditure Survey documents these differences.

**Example** (2023 CE Survey):
- Q1 spends 31% of budget on food vs Q5's 27%
- Q1 spends 34% on housing vs Q5's 33%  
- Q1 spends 4% on recreation vs Q5's 6%

If food inflates at 4% while recreation inflates at 1%, Q1 experiences higher effective inflation.

**Unemployment Exposure**: While we currently use national unemployment for all groups (data limitation), future versions could incorporate:
- Industry-specific unemployment (construction, services, etc.)
- Education-level unemployment rates
- Part-time vs full-time job availability

### 2.3 Formula Derivation

**Step 1**: Compute group-specific inflation
```
Inflation_q = Σ_{c} weight_{q,c} × CPI_inflation_c
```
Where:
- q = income quintile (Q1, Q2, Q3, Q4, Q5)
- c = expenditure category (food, housing, etc.)
- weight_{q,c} = budget share for quintile q, category c
- CPI_inflation_c = 12-month inflation rate for category c

**Step 2**: Measure labor market slack
```
Slack = U-3 unemployment rate (or U-6 for alternative)
```

**Step 3**: Combine into DMI
```
DMI_q = scale × (α × Inflation_q + (1-α) × Slack)
```

**Parameters**:
- α = 0.5 (equal weights on inflation and unemployment)
- scale = 2.0 (for historical comparability with Misery Index)

**Parameter Rationale**:
- α = 0.5: No strong theoretical reason to weight one component more than the other. Equal weights are a neutral starting point.
- scale = 2.0: The traditional Misery Index (no scaling, α=1 implicitly) produced values around 10-15 in the 1970s. Scaling by 2 brings DMI into a similar range.

**Alternative**: Researchers can set α based on data (e.g., regress consumer sentiment on inflation/unemployment) or use α=1 (inflation only) to focus purely on distributional inflation.

---

## 3. Data Sources

### 3.1 Consumer Expenditure Survey (CE)

**Purpose**: Provides income quintile-specific expenditure patterns.

**Provider**: U.S. Bureau of Labor Statistics (BLS)

**Frequency**: Annual

**Sample**: ~16,000 households per year (rotating panel)

**Vintage Used**: 2023 (Table 1203 - "Income before taxes: Annual expenditure means, shares, standard errors, and coefficients of variation, by quintiles of income before taxes")

**Categories**: 8 major groups aligned with CPI structure
- Food and beverages
- Housing
- Apparel
- Transportation
- Medical care
- Recreation
- Education and communication
- Other goods and services

**Limitations**:
1. **Sample size**: Smaller samples for Q1 (lowest income) → larger standard errors
2. **Recall bias**: Self-reported expenditures may be inaccurate
3. **Vintage lag**: 2023 weights may not reflect 2024 spending patterns
4. **No regional variation**: National averages only

**Future Enhancement**: Incorporate historical weight vintages (2011-2023) for more accurate historical backfilling.

### 3.2 Consumer Price Index (CPI-U)

**Purpose**: Measures price changes for urban consumers.

**Provider**: U.S. Bureau of Labor Statistics (BLS)

**Frequency**: Monthly

**Series**: 8 category-level series (not seasonally adjusted)
- Example: `CUUR0000SAF` = Food and beverages

**Coverage**: U.S. national average (87% of population)

**Base Period**: Index = 100 in 1982-1984

**Inflation Calculation**:
```
Inflation_t = (CPI_t / CPI_{t-12} - 1) × 100
```
12-month horizon smooths volatility and captures wage bargaining periods.

**Limitations**:
1. **Substitution bias**: Households switch to cheaper goods, but CPI lags
2. **Quality adjustment**: New products, quality changes hard to capture
3. **Geographic heterogeneity**: No regional DMI currently
4. **Owner-equivalent rent**: Controversial housing cost methodology

### 3.3 Current Population Survey (CPS)

**Purpose**: Measures labor force status.

**Provider**: U.S. Bureau of Labor Statistics (BLS) + Census Bureau

**Frequency**: Monthly

**Sample**: ~60,000 households

**Unemployment Definitions**:
- **U-3 (Baseline)**: Unemployed as % of labor force
  - Currently without work
  - Actively sought work in past 4 weeks
  - Available for work
  - Series ID: `LNS14000000`

- **U-6 (Alternative)**: Broader measure
  - U-3 + discouraged workers + marginally attached + part-time for economic reasons
  - Series ID: `LNS13327709`

**Limitation**: National rates only. No income quintile-specific unemployment available from BLS. This is a **major limitation** of current DMI—we apply the same slack measure to all quintiles.

**Future Enhancement**: Explore proxy measures like industry-weighted unemployment (if quintiles differ in industry composition) or education-weighted unemployment.

---

## 4. Methodology

### 4.1 Weight Extraction

**Input**: CE Table 1203 (Excel file)

**Process**:
1. Download from BLS website
2. Extract average annual expenditures for each quintile × category
3. Convert to shares: `weight = expenditure / total_expenditure`
4. Validate: Weights sum to 1.0 per quintile

**Output**: `data/curated/weights_by_group_2023.json`

**Example**:
```json
{
  "vintage": 2023,
  "rows": [
    {"group_id": "Q1", "category_id": "CPI_FOOD_BEVERAGES", "weight": 0.3109},
    {"group_id": "Q1", "category_id": "CPI_HOUSING", "weight": 0.3352},
    ...
  ]
}
```

### 4.2 Inflation Calculation

**Input**: Monthly CPI levels for 8 categories from BLS API

**Process**:
1. Fetch category-level CPI series (2009-2024 for backfill)
2. Convert BLS period codes (M01-M12) to YYYY-MM format
3. Pivot from long to wide format (categories as columns)
4. For reference period t and each category c:
   ```
   price_relative_c = CPI_{t,c} / CPI_{t-12,c}
   inflation_c = (price_relative_c - 1) × 100
   ```
5. For each quintile q:
   ```
   inflation_q = Σ_c weight_{q,c} × inflation_c
   ```

**Quality Check**: Q3 inflation should closely match BLS headline CPI (weights are close to average household).

**Output**: Inflation rate (%) for each quintile

**Example (Nov 2024)**:
- Q1: 2.68%
- Q2: 2.65%
- Q3: 2.55%
- Q4: 2.51%
- Q5: 2.45%

**Observation**: Higher-income quintiles experienced slightly lower inflation (0.23pp gap Q1-Q5).

### 4.3 Slack Measurement

**Input**: Monthly unemployment rate from BLS API

**Process**:
1. Fetch U-3 series (`LNS14000000`) or U-6 for alternative
2. Extract value for reference period
3. Use as slack measure (same value for all groups)

**Output**: Single unemployment rate (%) applied to all quintiles

**Limitation**: Assumes uniform unemployment exposure across income groups.

### 4.4 DMI Computation

**Input**: Inflation by quintile, slack rate, parameters (α, scale)

**Process**:
```python
for quintile in [Q1, Q2, Q3, Q4, Q5]:
    dmi = scale * (alpha * inflation[quintile] + (1 - alpha) * slack)
```

**Output**: DMI value for each quintile

**Interpretation**:
- **DMI = 10**: Economic pressure equivalent to 5% inflation + 5% unemployment
- **DMI = 6**: Lower pressure (e.g., 2.5% inflation + 4% unemployment)
- **DMI = 15**: High pressure (recession levels)

**Historical Context**:
- 2011-2012: DMI ~10-13 (post-Great Recession recovery)
- 2015-2019: DMI ~6-8 (low unemployment, moderate inflation)
- 2020: DMI spike to ~13 (COVID unemployment shock)
- 2021-2024: Gradual decline from inflation spike

### 4.5 Uncertainty Quantification

**Method**: Bootstrap simulation (1000 iterations)

**Rationale**: CE survey weights have sampling error, but BLS does not publish standard errors at our granularity (quintile × category).

**Approach**:
1. **Assume** coefficient of variation (CV) = 5% for all weights
   - Conservative estimate based on CE published SEs for broader aggregates
   - Lower quintiles likely have higher CV (smaller samples)
   
2. For each bootstrap iteration (i=1...1000):
   ```python
   # Perturb weights
   for each weight w:
       w_perturbed ~ Normal(mean=w, std=w * 0.05)
       w_perturbed = max(0.001, w_perturbed)  # Ensure positive
   
   # Renormalize
   for each quintile:
       weights_quintile = weights_quintile / sum(weights_quintile)
   
   # Recompute DMI
   inflation_i = compute_inflation(cpi, weights_perturbed)
   dmi_i = 2.0 * (0.5 * inflation_i + 0.5 * slack)
   ```

3. Compute statistics:
   ```python
   dmi_point_estimate = median(dmi bootstrap samples)
   ci_lower = percentile(dmi, 2.5)
   ci_upper = percentile(dmi, 97.5)
   se = std(dmi)
   ```

**Results (Nov 2024)**:
- Q1: DMI = 6.88 [6.83, 6.94], SE = 0.027
- Average CI width: 0.12 DMI points

**Interpretation**: Statistical uncertainty from weights is small (~0.12 points). Actual uncertainty is larger because CPI and unemployment also have sampling error (not quantified here).

**Caveats**:
1. Assumes normal distribution for weight perturbations (may not be accurate)
2. Ignores CPI sampling error (CPI is based on large price samples, small SEs)
3. Ignores unemployment sampling error (CPS has ~60k households, SEs available but not used)
4. CV=5% assumption not validated with actual CE microdata

**Future Work**: 
- Use CE microdata to estimate actual weight SEs
- Incorporate CPI and unemployment sampling errors
- Compare bootstrap to analytical variance propagation

---

## 5. Alternative Specifications

User's should consider multiple specifications for robustness.

### 5.1 U-6 Unemployment Alternative

**Motivation**: U-3 may understate labor market slack during periods with high underemployment or discouraged workers.

**Modification**: Replace U-3 with U-6 in DMI formula

**Results (Nov 2024)**:
- U-3 rate: 4.2% → U-6 rate: 7.7%
- Q1 DMI: 6.85 (baseline) → 10.38 (U-6) [+3.53 points]
- Average increase: +3.50 points across all quintiles

**When to Use**:
- Recession analysis (2008-2009, 2020)
- Periods of high part-time employment
- Comparing business cycle peaks/troughs

**Data Limitation**: U-6 only available 1994+, restricts historical backfill

### 5.2 Core CPI Alternative

**Motivation**: Food and energy prices are volatile. Core inflation may better reflect persistent price pressures.

**Modification**: Exclude `CPI_FOOD_BEVERAGES` from weights, renormalize remaining categories

**Results (Nov 2024)**:
- Q1 inflation: 2.68% (headline) → 2.83% (core) [+0.15pp]
- Q1 DMI: 6.88 (headline) → 7.03 (core) [+0.15 points]
- Average DMI difference: +0.13 points

**Interpretation**: In Nov 2024, food prices inflated *slower* than core items, so excluding food raises DMI slightly. In periods of food price spikes (e.g., 2021-2022), core DMI would be lower.

**When to Use**:
- Assessing underlying inflation trends
- Periods of commodity price shocks
- Comparing to Federal Reserve's core inflation focus

**Limitation**: We exclude only food, not energy (energy is embedded in transportation, housing). Official BLS core CPI (CUSR0000SA0L1E) would be more comprehensive but requires different methodology.

### 5.3 Specification Comparison

| Specification | Q1 DMI (Nov 2024) | Use Case |
|---------------|-------------------|----------|
| **Baseline** (U-3, Headline) | 6.85 | General purpose |
| **U-6** | 10.38 | Recessions, underemployment |
| **Core CPI** | 7.03 | Underlying inflation |
| **U-6 + Core** (possible) | 10.53 | Maximum conservatism |

**Recommendation**: Report baseline prominently, note alternatives in footnotes.

---

## 6. Validation & Quality Assurance

### 6.1 Internal Validation

**Weight Sum Check**: Verified programmatically
```python
for quintile in [Q1, Q2, Q3, Q4, Q5]:
    assert abs(sum(weights[quintile]) - 1.0) < 1e-6
```

**Inflation Contribution Sum**: Category contributions sum to group inflation
```python
assert abs(sum(contributions) - total_inflation) < 0.01
```

**Monotonicity**: Generally Q1 ≥ Q2 ≥ Q3 ≥ Q4 ≥ Q5
- Not always true (depends on category inflation patterns)
- Nov 2024: Q1 (6.88) > Q5 (6.65) [0.23 point spread]

**Bounds Checking**:
- DMI > 0 (inflation and unemployment are non-negative)
- DMI < 50 (sanity check, historical max ~13)
- Inflation -5% to +25% (deflation to hyperinflation range)

### 6.2 External Validation

**BLS Headline CPI Comparison**:
- Q3 inflation should ≈ BLS headline CPI
- Nov 2024: Q3 = 2.55%, BLS headline = 2.6% (very close ✓)

**DMI Tracks Business Cycles**:
- Increases during recessions (2008, 2020)
- Decreases during expansions (2015-2019, 2021-2024)
- Correlates with consumer sentiment indices (Michigan, Conference Board)

**Cross-Quintile Patterns**:
- Lower quintiles typically have higher DMI (spend more on necessities)
- Spread widest during food/energy shocks
- Convergent during service-driven inflation (housing, medical care)

### 6.3 Automated QA

**Schema Validation**: JSON files match expected structure
```python
jsonschema.validate(instance=dmi_release, schema=dmi_schema)
```

**Historical Consistency**: No breaks in time series
- All periods 2011-01 to 2024-11 present
- No missing values
- No suspiciously large month-over-month changes (>3 DMI points)

**CI Validity**: Confidence intervals are sensible
- Point estimate within CI bounds
- CI width > 0
- Lower bound < upper bound

---

## 7. Historical Trends (2011-2024)

### 7.1 Overview

**Period**: 167 months (2011-01 to 2024-11)  
**Observations**: 835 (167 periods × 5 quintiles)

**Key Statistics** (Q1 DMI):
- Mean: 9.73
- Median: 9.62
- Min: 6.54 (2024-09)
- Max: 13.88 (2011-09 / 2020-04)
- Current (2024-11): 6.88 (15th percentile)

### 7.2 Major Periods

**Post-Great Recession (2011-2012)**:
- DMI: 10-13
- High unemployment (9%) + moderate inflation (2-3%)
- Gradual decline as labor market recovered

**Low Inflation Era (2015-2019)**:
- DMI: 6-8
- Low unemployment (3.5-4.5%) + low inflation (1-2%)
- Economic expansion, Fed at/near 2% target

**COVID Shock (2020)**:
- DMI spike to ~13 (April 2020)
- Unemployment surge (14.8% in April)
- Rapid recovery as restrictions eased

**Inflation Surge (2021-2022)**:
- DMI: 10-12
- Low unemployment (3.5%) but high inflation (6-9%)
- Supply chain disruptions + demand recovery

**Disinflation (2023-2024)**:
- DMI: 6.5-7.5
- Inflation declining from peak, unemployment stable
- Current DMI among lowest in 13-year history

### 7.3 Quintile Divergence

**Measure**: Q5 - Q1 DMI spread

**Historical Pattern**:
- Average spread: -0.15 (Q1 typically 0.15 points higher)
- Widest spread: -0.52 (2021-06, food inflation spike)
- Narrowest: +0.05 (2024-04, service inflation dominant)

**Interpretation**: Lower-income households usually face higher DMI, but gap is small (~0.15 points). Food price shocks widen the gap; housing/service inflation narrows it.

### 7.4 Correlation with Other Indices

**Traditional Misery Index**: r = 0.92 (very high)
- DMI and Misery Index track closely
- DMI provides distributional detail Misery Index lacks

**Consumer Sentiment (Michigan)**: r = -0.78 (negative correlation)
- Higher DMI → lower confidence
- DMI is less volatile than sentiment

**Stock Market (S&P 500)**: r = -0.45 (negative correlation)
- Higher DMI → lower stocks (during recessions)
- Weaker relationship during 2021-2022 (stocks up, DMI up)

---

## 8. Limitations & Future Work

### 8.1 Current Limitations

**1. Single CE Weights Vintage (2023)**
- Applying 2023 weights to 2011 data assumes spending patterns unchanged
- Reality: Households adjust—substitute goods, change categories
- Impact: Historical DMI may be biased if spending patterns shifted

**Future**: Incorporate historical CE vintages (2011-2023 available)

**2. No Geographic Variation**
- National DMI only
- Coastal cities experience different inflation than rural areas
- Regional unemployment differs (e.g., Detroit vs San Francisco)

**Future**: Regional DMI (state or metro level) using regional CPI + local unemployment

**3. No Quintile-Specific Unemployment**
- All quintiles use national unemployment
- Reality: Lower-income workers may face higher job loss risk
- Impact: Understates Q1 DMI during recessions

**Future**: Industry-weighted unemployment (if industry composition differs by quintile)

**4. Simplified Uncertainty Quantification**
- Bootstrap assumes 5% CV for weights (not validated)
- Ignores CPI and unemployment sampling error
- Confidence intervals underestimate total uncertainty

**Future**: Use CE microdata to estimate actual weight SEs; incorporate all error sources

**5. No Demographics**
- Age, family structure, education not considered
- Single-parent households face different pressures than two-income couples
- Young workers vs retirees have different inflation baskets

**Future**: Demographic-specific DMI (e.g., by age group, family type)

### 8.2 Methodological Extensions (v0.2.0)

**1. Dynamic Weights**
- Allow weights to evolve over time (annual updates)
- Improves historical accuracy
- Requires consistent CE data processing pipeline

**2. Official Core CPI**
- Use BLS core CPI series (CUSR0000SA0L1E) instead of manual exclusion
- More comprehensive (excludes energy too)
- Requires recalculating weights without food/energy categories

**3. Confidence Intervals for Full Time Series**
- Backfill 2011-2024 with CIs
- Visualization: Shaded bands on time series chart
- Requires ~30 min compute time (167 periods × 1000 bootstrap × 5 groups)

**4. Higher-Frequency Updates**
- BLS publishes CPI mid-month
- Could update DMI ~15th of each month instead of monthly GitHub Actions
- Requires webhook or scheduled task

**5. Subnational DMI**
- Regional CPI series available from BLS
- Regional unemployment from BLS
- Challenge: CE weights may not be representative for small regions

### 8.3 Data Gaps

**Ideal But Unavailable**:
1. Quintile-specific unemployment rates (CPS doesn't publish)
2. Monthly CE weights (CE is annual only)
3. Income quintile definitions matched across CE and CPS (different surveys, definitions)
4. Real-time data (CE lags by ~6 months, annual only)

**Workarounds**:
1. Use industry-weighted unemployment as proxy
2. Interpolate or carry forward weights monthly
3. Accept definitional differences as limitation
4. Use most recent CE vintage for nowcasting

---

## 9. References

### Data Sources

Bureau of Labor Statistics (2024). Consumer Expenditure Survey: Table 1203. https://www.bls.gov/cex/tables.htm

Bureau of Labor Statistics (2024). Consumer Price Index - All Urban Consumers (CPI-U). https://www.bls.gov/cpi/

Bureau of Labor Statistics (2024). Labor Force Statistics from the Current Population Survey. https://www.bls.gov/cps/

### Academic Literature

Aguiar, M., & Bils, M. (2015). Has consumption inequality mirrored income inequality? *American Economic Review*, 105(9), 2725-2756.

Argente, D., & Lee, M. (2020). Cost of living inequality during the Great Recession. *Journal of the European Economic Association*, 19(2), 913-952.

Case, A., & Deaton, A. (2020). *Deaths of Despair and the Future of Capitalism*. Princeton University Press.

Hobijn, B., & Lagakos, D. (2005). Inflation inequality in the United States. *Review of Income and Wealth*, 51(4), 581-606.

### Original Misery Index

Okun, A. M. (1970). *The Political Economy of Prosperity*. Brookings Institution.

---

## Appendix A: Data Dictionary

### DMI Release File (`dmi_release_YYYY-MM.json`)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `reference_period` | string | Period in YYYY-MM format | `"2024-11"` |
| `specification` | string | Variant identifier | `"BASELINE"`, `"U6"`, `"CORE_CPI"` |
| `description` | string | Human-readable description | `"DMI using U-3..."` |
| `parameters.alpha` | number | Inflation weight in formula | `0.5` |
| `parameters.scale_factor` | number | DMI scaling multiplier | `2.0` |
| `parameters.weights_year` | integer | CE weights vintage | `2023` |
| `dmi_by_group` | array | DMI values by quintile | See below |
| `summary_metrics` | object | Aggregate statistics | See below |
| `inflation_contributions` | array | Category breakdowns | See below |
| `metadata` | object | Computation metadata | See below |

### DMI Group Record

| Field | Type | Description |
|-------|------|-------------|
| `group_id` | string | Income quintile (`"Q1"` to `"Q5"`) |
| `dmi` | number | DMI value (point est or median) |
| `inflation` | number | Group-specific inflation (%) |
| `slack` | number | Unemployment rate (%) |
| `dmi_ci_lower` | number | 95% CI lower bound (optional) |
| `dmi_ci_upper` | number | 95% CI upper bound (optional) |
| `dmi_se` | number | Standard error (optional) |

---

## Appendix B: Replication Guide

### Software Requirements

- Python 3.9+
- Libraries: `pandas`, `numpy`, `requests`, `jsonschema`
- Optional: `matplotlib` for charts

### Step-by-Step

**1. Clone Repository**
```bash
git clone https://github.com/dmianalysis/dmi.git
cd dmi
```

**2. Install Dependencies**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. Set BLS API Key** (optional, increases rate limits)
```bash
export BLS_API_KEY="your_key_here"
```

**4. Compute DMI for Latest Period**
```bash
./venv/bin/python -m scripts.compute_dmi
```

**5. Compute with Confidence Intervals** *(v0.1.12: not part of the shipped contract)*
```bash
# Bootstrap CI generation was part of the withdrawn v0.1.10 pipeline and is
# NOT re-validated under v0.1.12. `latest_with_ci` is emitted only when a
# `dmi_release_<period>_with_ci.json` happens to exist for the current
# period; the v0.1.12 default pipeline does not produce that file.
./venv/bin/python -m scripts.compute_dmi_with_ci --period 2024-11 --bootstrap 1000
```

**6. Run Alternative Specifications** *(v0.1.12: Baseline + Slack-Plus only)*
```bash
# `scripts.compute_dmi` produces BOTH Baseline and Slack-Plus in a single
# run. The previously advertised `compute_dmi_u6` and `compute_dmi_core`
# entry points are retired: the U-6 companion is now `_slack_plus`, and
# Core was withdrawn (docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md).
./venv/bin/python -m scripts.compute_dmi
```

**7. View Results**
```bash
cat data/outputs/dmi_release_2024-11.json
```

**8. Launch Web Dashboard**
```bash
cd web
python3 -m http.server 8000
# Open browser to http://localhost:8000
```

### Historical Backfill *(v0.1.12: legacy tooling — not re-validated)*

```bash
# The v0.1.10 backfill emitted a `dmi_timeseries_2010_2024.json` under
# published/. In v0.1.12 the public timeseries is Baseline-only at
# `data/outputs/published/dmi_timeseries.json` and its coverage begins at
# the earliest re-validated period (2025-12). The 2011-2024 series has
# NOT been re-validated under v0.1.12 — see §7 status banner at the top
# of this document.
./venv/bin/python -m scripts.backfill_historical
```

---

## Citation

**Suggested Format**:

> Williams, T.C. (2024). Distributional Misery Index: Measuring Economic Pressure Across Income Groups. Methodology Note v0.1.9.

**BibTeX**:
```bibtex
@techreport{williams2024dmi,
  title={Distributional Misery Index: Measuring Economic Pressure Across Income Groups},
  author={Williams, T.C.},
  year={2024},
  institution={Independent Research},
  type={Methodology Note},
  version={0.1.9}
}
```

---

**Contact**: For questions, errors, or suggestions, please open an issue on GitHub or email [contact info].

**Last Updated**: December 17, 2024
