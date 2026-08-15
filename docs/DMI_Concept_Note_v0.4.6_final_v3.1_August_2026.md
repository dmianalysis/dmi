---
title: "The Distributional Misery Index (DMI)"
subtitle: "Making the Five Economies Visible"
author: "Thomas C. Williams"
document_type: "Concept Note"
version: "0.4.6"
date: "v0.4.6 | August 2026"
doi: "10.5281/zenodo.21881671"
license: "CC BY 4.0"
---

```{=latex}
\begin{center}
\textbf{DOI:} 10.5281/zenodo.21881671
\end{center}
```

**Status:** Public reference concept note; operational index with continuing methodological development  
**Framework:** *Five Economies* (concept) / *By Fifths analysis* (method)  
**Project site:** [dmianalysis.org](https://dmianalysis.org/)

---

## Abstract

The **Distributional Misery Index (DMI)** is a distribution-aware extension of the classic Misery Index, commonly defined as the sum of the inflation rate and the unemployment rate. The classic measure offers a compact gauge of macroeconomic discomfort, but it treats national averages as though they describe a common household experience. The DMI adds the question that the aggregate measure leaves unanswered: **for whom?**

The DMI applies the **Five Economies** framework—the proposition that a single national economy can produce materially different lived economic conditions across the income distribution—and operationalizes it through **By Fifths analysis**, which reports results for five income quintiles. It combines group-weighted consumer-price inflation with a transparent measure of labor-market slack. The recurring public releases are currently national; geographic differentiation is a planned but unimplemented extension.

This initial concept note presents the Distributional Misery Index (DMI) and its small, versioned specification architecture. The operational family currently comprises two specifications: Baseline combines quintile-weighted headline inflation with U-3 unemployment, while Slack-Plus substitutes the broader U-6 measure of labor underutilization where comparable data are available. Core is an intended third specification that would test whether the distributional pattern persists after food and energy are excluded; it has not yet been implemented, validated, or adopted as part of the operational public family. A manifest-driven monthly release process separates reference periods, data vintages, methodological versions, operational specifications, and quality-assurance results.

The note also clarifies the relationship between the DMI and newer distributional price research. In particular, the U.S. Bureau of Economic Analysis now publishes an income-stratified Personal Consumption Expenditures price index. That series creates an important comparison and validation track, but it does not make a CPI-based DMI redundant: the two systems differ in scope, weighting, and purpose. Recent evidence that income-group inflation gaps may be modest or regime-dependent reinforces a central discipline of the project: the Five Economies framework is a reason to **measure heterogeneity**, not to presume its direction or magnitude.

The canonical public result is the five-quintile profile. Four summary outputs describe different features of that profile: **DMI Median** reports its middle value; **DMI Stress** reports its maximum; **Income Pressure Spread** reports the nonnegative maximum-minus-minimum distance; and **Income Pressure Tilt** reports the signed Q1-minus-Q5 endpoint contrast. Because the operational v0.1.12 method applies the same labor-slack rate to all five quintiles, the current cross-quintile Spread and Tilt arise from the distributional inflation component. Quintile-specific labor slack remains a research extension, not a released result.

The DMI is descriptive rather than prescriptive. It is intended to improve visibility, comparison, and empirical inquiry—not to serve as a comprehensive welfare index, a causal model, or a mechanical policy rule.

**Keywords:** Misery Index; inflation; unemployment; labor underutilization; income quintiles; distributional measurement; CPI; PCE; household hardship; economic communication

**Audience note:** This document is the project’s methodological and conceptual reference. A shorter policymaker brief and a dashboard-level public explainer should be derived from it rather than requiring every audience to enter through the full reference note.

---

## 1. The problem: one headline, unequal conditions

### 1.1 Aggregate indicators are necessary but incomplete

GDP growth, headline inflation, and the national unemployment rate are indispensable measures. They are also aggregates. They answer questions about the economy as a whole but often cannot answer how current conditions are distributed among households.

Households differ in at least four economically important ways:

- **Consumption:** They buy different mixes of food, housing, transportation, medical care, education, financial services, and discretionary goods.
- **Labor-market position:** They differ in occupation, industry, employment security, hours, bargaining power, and exposure to cyclical displacement.
- **Adjustment capacity:** They possess different liquid savings, access to credit, ability to substitute among goods, geographic mobility, and tolerance for delayed consumption.
- **Place:** Prices, wages, housing costs, and labor-market slack vary across states and metropolitan areas.

The same national inflation and unemployment rates can therefore coexist with materially different economic pressures. An aggregate can be accurate while remaining incomplete as a description of lived conditions.

### 1.2 The classic Misery Index and its missing question

The Misery Index—commonly attributed to Arthur Okun and described in the literature as the Economic Discomfort Index—adds the annual inflation rate to the unemployment rate. Its appeal lies in compression: it combines two salient sources of macroeconomic stress in a number that non-specialists can readily understand. The attribution should be stated with care: the measure is widely associated with Okun, but the project has not identified a formal Okun paper introducing it.

Its limitation is equally clear. The index implicitly treats the incidence of inflation and labor-market weakness as uniform. In reality:

- expenditure weights vary across the income distribution;
- inflation across categories is uneven;
- unemployment does not capture all labor underutilization;
- labor-market conditions vary by place and population; and
- equal national averages can conceal different combinations of price and employment pressure.

The DMI preserves the classic measure’s communicative simplicity while adding the distributional question: **who is experiencing the pressure?**

---

## 2. Framework and method

### 2.1 The project hierarchy

Three related ideas should be kept distinct:

| Layer | Name | Function |
|---|---|---|
| Framework | **Five Economies** | Describes how a single national economy can generate different economic realities across income strata. |
| Method | **By Fifths analysis** | Computes and reports a measure for five income quintiles. |
| Flagship application | **Distributional Misery Index** | Applies the framework and method to contemporaneous inflation and labor-market pressure. |

The DMI is the first implemented application of the Five Economies framework. The framework is broader than the DMI and can support other domain-specific measures, but those measures require their own constructs, data, validation, and limitations.

### 2.2 What “Five Economies” claims

The framework makes a modest, testable claim:

> A national average may conceal economically meaningful differences across income fifths; those differences should be measured before they are assumed away.

It does **not** claim that:

- every indicator will differ substantially by quintile;
- the lowest quintile must always experience the highest measured pressure;
- quintiles are internally homogeneous;
- income is the only relevant axis of difference; or
- five groups reveal every important distributional pattern.

The number five is a reporting convention chosen for interpretability, relative statistical stability, and public communication. Where the underlying data support greater detail, the project may **compute fine and report coarse**—for example, estimating at decile level while publishing quintile results.

### 2.3 Why quintiles rather than a single “average household”

Quintiles provide a useful middle ground. A single national figure suppresses distributional structure, while very fine segmentation can create unstable estimates and communication burdens. Five equally populated income groups make it possible to see gradients, crossovers, and divergence without implying that each household within a fifth has the same experience.

By Fifths analysis is therefore a lens, not an ontology. Other decompositions—age, race and ethnicity, family structure, tenure, disability, geography, or occupation—may reveal different patterns. The DMI begins with income fifths because income is closely related to expenditure composition, financial buffers, and labor-market position, and because public data permit a reasonably transparent implementation.

### 2.4 Time horizon as a structural dimension

Five Economies applications can operate on different time horizons. The DMI measures **contemporaneous pressure**: price change and labor-market slack during a defined reference period. Place-based intergenerational-mobility measures summarize **long-run outcomes and structural capacity**. The developing AI Labor Risk Index measures a **current prospective risk position** rather than either present hardship or a realized long-run outcome.

These lenses can be interpreted together, but they should not be collapsed into one number. A place can experience high current DMI pressure while retaining relatively strong historical mobility capacity, or low current pressure while exhibiting weak long-run mobility. The pairing is diagnostic, not causal. Structural context does not enter the DMI formula unless a separately named future specification is proposed, justified, and validated.

---

## 3. Conceptual target and index structure

### 3.1 The target construct

The DMI measures **contemporaneous economic pressure arising from consumer-price change and labor-market slack**. It is designed to retain the intuition and scale of the classic Misery Index while making the inflation component distribution-aware and the slack component specification-aware.

For income group $g$, geography $r$, period $t$, and specification $s$:

$$
\mathrm{DMI}^{(s)}_{g,r,t} =
\mathrm{scale\_factor}
\left[
\mathrm{alpha}\,\pi^{(s)}_{g,r,t} +
(1-\mathrm{alpha})S^{(s)}_{r,t}
\right]
$$

where:

- $\pi^{(s)}_{g,r,t}$ is the price-change measure experienced by income group $g$;
- $S^{(s)}_{r,t}$ is the selected measure of labor-market slack;
- `alpha` is the relative weight assigned to price pressure; and
- `scale_factor` is the multiplier that preserves the desired index scale.

The current baseline uses `alpha = 0.5` and `scale_factor = 2.0`. The resulting expression is numerically equivalent to adding inflation and slack:

$$
\mathrm{DMI}_{g,r,t}=\pi_{g,r,t}+S_{r,t}.
$$

Expressing the model with named parameters makes the weighting assumption explicit while preserving continuity with the classic index and the public data schema.

### 3.2 Why equal weighting remains the baseline

Equal weighting is not a claim that one percentage point of inflation creates exactly the same welfare loss as one percentage point of unemployment for every group. It is a transparent convention inherited from the classic Misery Index.

Keeping the baseline simple has three advantages:

1. it avoids concealing normative judgments inside the published headline;
2. it makes the measure easy to reproduce and explain; and
3. it permits alternative weighting schemes to be evaluated openly as sensitivity analyses.

Quintile-specific `alpha` values remain a research extension. They should not replace the baseline unless a published calibration method—empirical, subjective-well-being-based, survey-based, or welfare-theoretic—demonstrates that the added complexity improves interpretation or external validity.

### 3.3 Additive structure and decomposability

The DMI’s additive form permits each result to be decomposed into:

- a **price-pressure contribution**; and
- a **labor-slack contribution**.

The price contribution can be decomposed further by category. This is essential for interpretation. Two quintiles can have the same DMI value for different reasons, and the same quintile can reach the same value in different periods through a different combination of inflation and slack.

The DMI is therefore best understood as a compact front end to an inspectable profile—not as a number that should be read without its components.

---

## 4. Component construction

### 4.1 Group-weighted inflation

The CPI-based implementation estimates inflation for each income quintile by reweighting consumer-price changes with group-specific expenditure shares.

A simplified representation is:

$$
\pi_{g,t} =
\sum_{c=1}^{C}
w_{g,c,v}\Delta p_{c,t},
\qquad
\sum_{c=1}^{C}w_{g,c,v}=1,
$$

where:

- $c$ indexes consumption categories;
- $w_{g,c,v}$ is the expenditure share for group $g$, category $c$, and weight vintage $v$;
- $\Delta p_{c,t}$ is the relevant CPI category price change.

The operational process uses:

1. BLS CPI component series;
2. Consumer Expenditure Surveys expenditure data by income quintile;
3. a documented category concordance between expenditure and price series;
4. a declared expenditure-weight vintage; and
5. explicit rules for missing, revised, or unmatched categories.

The purpose is not to claim that every household within a quintile experiences the resulting rate. It is to estimate how differing expenditure composition changes the inflation signal for the group as a whole.

### 4.2 What group-weighted inflation captures—and misses

Group weighting captures variation in expenditure composition. It does not fully capture:

- differences in prices paid for the same nominal item;
- differences in product quality, retailer, package size, or location;
- household-level substitution;
- uncompensated time costs;
- access constraints or shortages;
- the effect of wealth, debt structure, or fixed-rate borrowing;
- transfers, taxes, or employer-paid consumption; or
- heterogeneity within a quintile.

The resulting estimates are distributional price indexes, not household-specific cost-of-living measures.

### 4.3 Labor-market slack

The second component represents the degree to which available labor is not fully employed. No single statistic captures every form of labor-market pressure, so the DMI identifies the slack measure as part of the specification.

The two current measures are:

- **U-3:** the official unemployment rate; and
- **U-6:** U-3 plus marginally attached workers and people working part time for economic reasons, expressed relative to the civilian labor force plus marginally attached workers.

U-3 preserves direct continuity with the classic Misery Index. U-6 captures a wider boundary of labor underutilization and can reveal deterioration that does not appear fully in the headline unemployment rate.

### 4.4 The current limitation: slack is not quintile-specific

In the operational v0.1.12 implementation, the slack term is shared across income quintiles in the national release. This is a methodological fact, not merely a default assumption. All cross-quintile variation in a given released specification therefore comes from the price component. A future geographic specification would need to declare its slack measure and geographic mapping explicitly.

This is a transparent approximation, not a claim that unemployment risk is evenly distributed. Neither an education-stratified proxy nor an occupation-stratified slack measure is part of the current released methodology, and no empirical result from either approach should be attributed to the operational DMI unless it has been reproduced, versioned, and published under a separately named research specification.

BLS Table A-4 documents persistent differences in unemployment by educational attainment, reinforcing that shared slack is a simplifying approximation. For reference period `2026-06`, seasonally adjusted unemployment among people age 25 and older ranged from 5.5 percent for those without a high-school diploma to 2.7 percent for those with a bachelor’s degree or higher. Educational-attainment groups are not income quintiles, however, so these data do not establish the magnitude or ordering of quintile-specific slack.

Candidate research approaches include:

- mapping education-specific unemployment rates to income groups through a declared crosswalk;
- estimating group-specific slack directly from Current Population Survey microdata, where sample size and seasonal-adjustment constraints permit; and
- constructing an occupationally weighted measure linking:

  - occupational employment and wage distributions;
  - unemployment or displacement patterns by occupation or industry; and
  - the occupational composition of workers associated with different income groups.

Each approach introduces additional population-universe, mapping, lag, estimation, and validation choices. A stratified extension should be added only when its evidence is strong enough to justify the complexity and its manifest identifies the stratification method, source universe, seasonal-adjustment treatment, crosswalk and mapping versions, and fallback rules.

### 4.5 Geography

The recurring public DMI is currently implemented and released at the national level only. State-level DMI is a planned extension for which some data-source and proxy design work exists; no state estimate has yet been implemented, validated, or published.

A future state-level specification would use official labor-market data and the best available price and expenditure mappings, with every proxy choice disclosed. Geographic implementation will require care because:

- BLS does not publish a complete monthly CPI for every state;
- local CPI coverage varies by metropolitan area and publication frequency;
- Consumer Expenditure Surveys geographic quintile tables are not equally available for every state and period; and
- a state estimate may therefore need to combine state-specific slack with broader price movements or expenditure weights.

If state-level results are eventually released, they should be labeled as structured comparative estimates under stated proxy rules, not as fully observed state-specific household price indexes. The state specification, proxy hierarchy, validation results, and release cadence should be published before any state ranking is presented as an operational DMI output.

### 4.6 Reference periods, release dates, and vintages

The DMI distinguishes:

- the **reference period** to which the economic conditions apply;
- the **release date** on which the DMI result is published;
- the **source-data vintage** used in the calculation;
- the **expenditure-weight year**; and
- the **methodology version**.

This distinction matters because component data arrive on different schedules and may later be revised. A DMI release is a reproducible estimate based on a declared information set, not an atemporal statement of the “true” value.

---

## 5. Current and intended DMI specifications

As of August 2026, the monthly workflow supports two operational specifications—Baseline and Slack-Plus. Core is defined as an intended third specification but is not yet operational.

| Specification | Status |  Price component | Slack component | Primary purpose |
|---|---|---|---|---|
| **Baseline** | Operational  | Quintile-weighted headline CPI inflation | U-3 unemployment | Canonical public DMI; maximum continuity with the classic Misery Index |
| **Slack-Plus** | Operational |  Same price construction as Baseline | U-6 labor underutilization, where comparable data are available | Shows broader labor stress that may be missed by headline unemployment |
| **Core** | Intended; not implemented or validated | Quintile-weighted inflation under the declared Core exclusion basket | U-3 unemployment | Would test whether distributional pressure persists when designated volatile categories are removed |

### 5.1 Baseline

Baseline remains the principal DMI. It is CPI-based, publicly interpretable, and directly comparable in structure to the traditional unemployment-plus-inflation measure.

### 5.2 Slack-Plus

Slack-Plus is not “the real unemployment rate,” nor is U-3 a false measure. The two specifications answer different questions. Baseline asks about official unemployment; Slack-Plus asks whether the picture changes when involuntary part-time work and marginal attachment are included.

National U-6 is available monthly. Subnational U-6 estimates are less frequent and are not interchangeable with monthly state U-3 series. No state Slack-Plus implementation currently exists; any future subnational version should be released only at geographic and temporal resolutions supported by comparable official data.

### 5.3 Core

The intended Core construction would remove food and energy price changes and renormalize the remaining expenditure weights within each quintile to examine persistence and breadth. A future release manifest would need to enumerate the exact excluded CPI series and the renormalization rule. An implementation that excludes a narrower or otherwise different basket is a different specification and should not silently inherit the same Core label.

Core has not yet been implemented or validated as an operational DMI specification. The current eight-category CPI–Consumer Expenditure mapping identifies food as a top-level category but embeds energy components within housing and transportation. It therefore cannot support a defensible exclusion of both food and energy. A valid implementation requires a finer-grained mapping that separates housing energy from other housing costs and motor fuel from other transportation costs, together with matching quintile expenditure weights, revised data acquisition, and specification-specific validation.

Until that work is completed and versioned, no monthly release, manifest entry, public summary, or output file labeled **Core** should be treated as a valid Core result. Any legacy artifact produced under the Core label using a narrower exclusion basket does not conform to this definition and should not be interpreted as an operational Core output.

Core would be analytically useful but should not displace Baseline as the main lived-pressure measure. Food and energy are not optional expenses simply because their prices are volatile; excluding them answers a different question.

### 5.4 Specification discipline

Each release should identify:

- specification name and version;
- inflation scope;
- slack measure and source series;
- `alpha` and `scale_factor`;
- expenditure-weight vintage;
- reference period;
- geographic scope and, for any future subnational release, proxy rules; and
- quality-assurance status.

If a research specification introduces group-specific slack, its manifest should additionally identify the stratification method, population universe, seasonal-adjustment treatment, crosswalk vintage, mapping version, and fallback rules. This prevents an apparently simple label such as “DMI” from hiding a change in construct.

---

## 6. Companion measures and alternative lenses

Not every economically relevant signal should be inserted into the DMI formula. The project instead uses companion measures where a concept answers a related but distinct question.

### 6.1 Income-stratified PCE comparison

In June 2026, the Bureau of Economic Analysis added an official **income-stratified Personal Consumption Expenditures price index** (ISPCEPX), providing inflation measures by income decile within the national accounts.

This development creates three opportunities:

1. **Benchmarking:** Compare the direction and magnitude of DMI’s CPI-based quintile inflation gaps with the BEA series.
2. **Construct comparison:** Explain how CPI and PCE scope, weights, and aggregation affect distributional results.
3. **Alternative specification:** Explore a DMI-PCE research variant without replacing the public CPI-based baseline.

Recent BEA research finds that income-stratified PCE inflation gaps can be smaller than gaps found in some CPI-based studies and that services disproportionately consumed by higher-income households can materially affect the result. The methodological implication is not that distributional inflation is unimportant. It is that its sign and magnitude are empirical questions that depend partly on index construction and economic regime.

### 6.2 Essentials Pressure

An **Essentials Pressure** view can isolate categories that are difficult to defer or avoid, such as:

- shelter;
- food;
- household energy;
- transportation;
- medical care; and
- other clearly defined necessities.

This view may be especially useful for public communication, but it requires an explicit and contestable definition of “essential.” It should remain a companion decomposition rather than be silently embedded in the baseline.

### 6.3 Wage Cushion or Purchasing-Power Offset

Price pressure is experienced relative to income growth. A **Wage Cushion** or **Purchasing-Power Offset** measure could compare group-relevant inflation with wage or income growth where compatible data are available.

This would answer a different question from the DMI:

- DMI: How much contemporaneous price and labor pressure is present?
- Wage Cushion: To what extent is nominal income growth offsetting price pressure?

Combining the two prematurely would reduce interpretability and risk double counting labor-market conditions.

### 6.4 Pipeline Pressure Monitor

Producer prices, import prices, commodity prices, freight costs, and wage costs may signal future consumer-price pressure. They should not be added directly to the DMI, because doing so would mix current household conditions with upstream indicators and create possible double counting.

A separate **Pipeline Pressure Monitor** can provide forward-looking context without changing the DMI’s contemporaneous construct.

### 6.5 Persistence notes

Short-term changes can be noisy. Release commentary may therefore distinguish:

- one-month movement;
- three-month direction;
- year-over-year pressure; and
- whether category contributions are broadening or narrowing.

These are interpretive aids, not additional index components.

### 6.6 Place-based mobility context

Research by Raj Chetty and collaborators shows that intergenerational mobility differs substantially across U.S. geographic areas. Later work also identifies cross-class economic connectedness as a strong predictor of upward mobility.

These measures provide a useful structural companion to the DMI:

- DMI asks where households are under pressure now.
- Place-based mobility measures ask how strongly a location has historically supported upward movement across generations.

The two should be displayed as separate measures with different reference periods, populations, and evidentiary meanings. Mobility context can help distinguish short-run stress from deeper structural constraint, but it does not explain a DMI reading, establish causation, or alter the DMI calculation.

---

## 7. Public outputs

The DMI is designed to publish a compact set of stable, inspectable outputs.

### 7.1 Quintile profile

The primary output is the five-value DMI profile:

$$
\left(
\mathrm{DMI}_{Q1},
\mathrm{DMI}_{Q2},
\mathrm{DMI}_{Q3},
\mathrm{DMI}_{Q4},
\mathrm{DMI}_{Q5}
\right).
$$

The profile should be treated as the core result. Summary metrics are conveniences and should not replace it.

### 7.2 DMI Median

**DMI Median** reports the median of the five DMI values:

$$
\mathrm{DMI\ Median}^{(s)}_{r,t} =
\operatorname{median}_{g \in \{Q1,\ldots,Q5\}}
\left(\mathrm{DMI}^{(s)}_{g,r,t}\right).
$$

It is the middle value after the five group-level results are ordered by DMI, not automatically the value for income quintile Q3. It is also not the population median of household-level pressure because the DMI is calculated at group level.

### 7.3 DMI Stress

**DMI Stress** reports the highest measured quintile value for the period and geography. It answers: where is the greatest pressure within the five-group profile?

The identity of the highest-stress quintile should be reported alongside the value. “Stress” does not mean clinical distress or prove hardship for every household in that group.

The September 2025 planning record proposed a 95th-percentile measure when national decile or finer-grained publication was contemplated. That proposal has been superseded for the canonical five-quintile output: DMI Stress is the maximum reported quintile value. Any future high-percentile statistic should carry a distinct label and define its underlying population and interpolation rule.

### 7.4 Income Pressure Spread

**Income Pressure Spread** reports the nonnegative distance between the most- and least-pressured quintiles:

$$
\mathrm{Spread}^{(s)}_{r,t} =
\max_g\left(\mathrm{DMI}^{(s)}_{g,r,t}\right) -
\min_g\left(\mathrm{DMI}^{(s)}_{g,r,t}\right).
$$

Spread measures the total separation visible in the five-value profile. It does not identify which end of the income distribution is under greater pressure; the most- and least-pressured group identifiers should therefore be reported with it.

### 7.5 Income Pressure Tilt

**Income Pressure Tilt** reports the signed endpoint contrast:

$$
\mathrm{Tilt}^{(s)}_{r,t} =
\mathrm{DMI}^{(s)}_{Q1,r,t} -
\mathrm{DMI}^{(s)}_{Q5,r,t}.
$$

A positive value means Q1 has higher measured pressure than Q5. A negative value means Q5 has higher measured pressure than Q1. Zero means only that the endpoints are equal; an interior quintile can still be the most- or least-pressured group.

Spread and Tilt therefore answer different questions. The pre-v0.1.12 `income_pressure_gap` field was ambiguous because it used one signed endpoint statistic to carry both dispersion and directional meaning. It has been retired from the public schema.

Under the current shared-slack specifications, the common slack term cancels from both measures:

$$
\mathrm{Spread}^{(s)}_{r,t} =
\mathrm{scale\_factor}\times\mathrm{alpha}
\left[
\max_g\left(\pi^{(s)}_{g,r,t}\right) -
\min_g\left(\pi^{(s)}_{g,r,t}\right)
\right],
$$

$$
\mathrm{Tilt}^{(s)}_{r,t} =
\mathrm{scale\_factor}\times\mathrm{alpha}
\left[
\pi^{(s)}_{Q1,r,t} -
\pi^{(s)}_{Q5,r,t}
\right].
$$

At the default values, `scale_factor × alpha = 1`. Substituting shared U-6 for shared U-3 raises DMI Median and DMI Stress by the same amount for every group but does not change Spread or Tilt for a given inflation profile.

In the Baseline release for reference period `2026-06`, Q4 was the most-pressured group and Q1 the least pressured; Spread was 0.22, while Tilt was $-0.20$ because Q5 exceeded Q1. This profile illustrates why both measures are needed: an endpoint contrast alone would have missed the interior maximum.

### 7.6 Contributions and future geography

Where available, releases should also show:

- price and slack contributions;
- major inflation-category contributions;
- the highest- and lowest-pressure quintiles;
- the current national view and, only after separate implementation and validation, state views;
- comparison with the classic Misery Index; and
- differences between Baseline and Slack-Plus and, after a valid Core implementation has been completed and released, comparisons with Core.

---

## 8. Release architecture and reproducibility

The DMI is not only a formula. It is a recurring public measurement process.

### 8.1 Monthly release cycle

The operational workflow:

1. checks whether required source releases are available;
2. retrieves or verifies source data;
3. preserves the relevant raw or source-aligned inputs;
4. applies declared mappings and weight vintages;
5. computes each supported specification;
6. runs specification-level and cross-release quality checks;
7. produces machine-readable outputs and a human-readable summary; and
8. updates the current-release pointers and archive.

### 8.2 Machine-readable manifests

The release system uses separate machine-readable files for distinct functions:

- `latest.json` identifies the current public release;
- `releases.json` indexes available releases and headline metrics;
- `specifications.json` defines the active operational specifications; and
- quality-assurance outputs record validation status and exceptions.

Public output metadata should include both a **schema version** and a **methodology version**. A schema change alters how data are represented; a methodology change alters how a measure is constructed or interpreted. The distinction is essential for downstream users.

These identifiers are independent. The methodology version—currently v0.1.12—governs how the DMI measures are constructed and interpreted. Schema versions govern the representation of particular machine-readable outputs and may differ by file. Document versions, such as this concept note's own version number, track revisions to explanatory reference materials. No one version string implies or determines another.

### 8.3 Revision policy

Source data may be revised, and mappings or code may be corrected. The project should distinguish:

- **source-data revisions**, where the methodology is unchanged;
- **methodological revisions**, where a construct, mapping, or rule changes;
- **technical corrections**, where an implementation error is repaired; and
- **presentation changes**, where labels or displays change without changing values.

Material revisions should retain the prior release, identify the reason for change, and state whether historical values were recomputed.

### 8.4 Quality assurance

Quality checks should include:

- completeness of expected quintiles and declared geographic scope, currently national only;
- expenditure-weight sums and missing-category thresholds;
- source-series freshness and reference-period alignment;
- comparison with prior releases and plausible change bounds;
- internal consistency between the five-value profile and summary metrics;
- exact reproduction of DMI Median, DMI Stress, Income Pressure Spread, and Income Pressure Tilt from the published quintile profile;
- consistency of the most- and least-pressured group identifiers with the profile extrema;
- nonnegativity of Spread and consistency of Tilt’s sign with the Q1-minus-Q5 ordering;
- cross-file consistency among release manifests; and
- explicit failure rather than silent substitution when a required source is unavailable.

The goal is not to eliminate uncertainty. It is to make the evidence chain visible enough that errors, revisions, and judgment calls can be found and contested.

### 8.5 Proportionate publication

The current public package emphasizes a lean, sustainable release process. A larger academic replication package—such as archived raw snapshots, Parquet datasets, extensive validation figures, and permanent release identifiers—should be expanded as evidence of external use, citation, or reuse justifies the maintenance burden.

---

## 9. Validation as an empirical program

The DMI should not be considered valid merely because its formula is plausible. Its value depends on whether the distributional profile contains information that aligns with independently observed household stress and improves on aggregate measures.

### 9.1 Principal validation questions

The research program should ask:

1. Does DMI move in the expected direction during known inflationary and labor-market stress episodes?
2. Does the quintile profile contain information not visible in the classic Misery Index?
3. Do DMI levels or changes align with independent hardship indicators?
4. Does Slack-Plus improve alignment when underemployment and marginal attachment rise?
5. Once Core has been implemented, do its results help distinguish transitory category shocks from broader pressure?
6. How sensitive are quintile gaps to CPI versus PCE scope and weighting?
7. Before any state extension is released, are its estimates and rankings robust to alternative geographic proxy choices?

### 9.2 External hardship proxies

Candidate validation variables include:

- difficulty paying usual household expenses;
- food insufficiency or food insecurity;
- rent, utility, or mortgage arrears;
- consumer-credit delinquency;
- eviction-related measures;
- use of savings or borrowing to meet ordinary expenses;
- consumer sentiment; and
- other timely indicators with documented population and geographic coverage.

The Census Bureau’s Household Trends and Outlook Pulse Survey is particularly useful for a lightweight validation panel because it includes measures such as food sufficiency and difficulty paying usual household expenses. Its sampling design, response rates, breaks in series, and changing collection model must be handled explicitly.

### 9.3 Validation is not causal inference

Correlation with hardship proxies would support criterion validity, but it would not show that DMI components caused the observed hardship. Both may respond to common economic forces, policy changes, or demographic composition.

The appropriate claims are comparative:

- whether DMI tracks independent stress signals;
- whether a particular specification performs better than another;
- whether distributional outputs add information beyond aggregates; and
- where the measure fails.

### 9.4 Robustness and falsifiability

The DMI should be tested under:

- alternative expenditure-weight vintages;
- alternative category mappings;
- U-3 versus U-6;
- headline versus the intended Core measure after implementation;
- CPI-based versus PCE-based distributional inflation;
- for any future state specification, alternative geographic proxy rules;
- Income Pressure Spread versus Income Pressure Tilt and other separately labeled full-profile dispersion measures; and
- plausible values or distributions for `alpha`.

A credible result may be that quintile differences are small in some periods. That finding would not invalidate the Five Economies framework. It would establish an empirical boundary: the distributional lens matters most when the components diverge enough to produce a meaningful profile.

### 9.5 Possible future calibration of `alpha`

Five calibration routes remain available:

1. **Predictive:** select weights that improve out-of-sample alignment with independent hardship proxies.
2. **Subjective-well-being-based:** estimate the relative association of inflation and unemployment with reported life satisfaction. Di Tella, MacCulloch, and Oswald (2001) and Blanchflower et al. (2014) provide important precedents, but their materially different implied tradeoffs support sensitivity analysis rather than automatic adoption of a single coefficient.
3. **Stated-preference:** directly elicit perceived tradeoffs between inflation and unemployment from different groups, with the usual cautions about survey framing and hypothetical choices.
4. **Welfare-theoretic:** derive weights from an explicit model with published assumptions.
5. **Uncertainty-based:** report results across plausible weight ranges rather than selecting one value.

Subjective-well-being regressions are not the same as directly eliciting respondent preferences, and neither route produces a value-free social welfare weight. Any calibrated specification should be published alongside, not silently substituted for, the equal-weight baseline until its stability and interpretation are established.

---

## 10. Interpretation and boundaries

### 10.1 What the DMI measures

The DMI measures a defined combination of:

- group-weighted consumer-price change; and
- measured labor-market slack.

The current operational series is best interpreted as an index of **national macroeconomic pressure viewed through income groups**. The broader framework is designed to support future place-based extensions, but those extensions are not yet operational DMI outputs.

### 10.2 What the DMI does not measure

The DMI is not:

- a complete welfare or well-being index;
- a poverty measure;
- a cost-of-living adjustment for an individual household;
- a measure of inequality in income or wealth;
- a measure of post-tax, post-transfer disposable income;
- a causal model of inflation or unemployment;
- a forecast;
- a probability that a household will experience hardship;
- a mechanical trigger for policy; or
- a ranking of which group “deserves” assistance.

It does not directly incorporate wealth buffers, debt service, taxes, transfers, health status, housing quality, family obligations, informal support, or long-run opportunity.

### 10.3 Visibility, not advocacy

The DMI is nonpartisan and descriptive. Its purpose is to make distributional patterns more visible and contestable. Different users may reasonably draw different policy conclusions from the same profile.

Neutrality does not require pretending that distributional effects do not exist. It requires:

- stating the construct clearly;
- using transparent data and methods;
- separating measurement from prescription;
- publishing limitations and revisions; and
- allowing results that challenge the project’s prior expectations.

---

## 11. Relationship to the wider Five Economies research program

### 11.1 Healthcare Burden

A future **Five Economies Healthcare Burden Index** would examine how premiums, out-of-pocket costs, access constraints, illness burden, and financial capacity interact across income fifths.

It should not be built by simply inserting medical CPI into the DMI. Healthcare burden is a different construct involving coverage, utilization, risk pooling, access, health need, and catastrophic exposure. It remains at the concept stage.

### 11.2 AI Labor Risk

The developing **Five Economies AI Labor Risk Index** addresses a forward-looking labor-market question distinct from current unemployment. Its current design direction separates:

- **substitution-risk exposure**, based on the task and occupational content of work;
- **adjustment vulnerability**, based on the worker’s and local labor market’s capacity to absorb change; and
- **adoption pressure**, reflecting the extent to which firms are actually deploying relevant technologies.

An unpublished internal working concept note developed in December 2025 proposed five candidate components—task exposure, complementarity-adjusted exposure, adjustment capacity, labor-market concentration, and employer adoption pressure—and left additive versus multiplicative aggregation open. Design work in June 2026 consolidated those ideas into a more interpretable architecture rather than treating five unlike components as interchangeable terms in a single weighted sum.

The proposed current core combines substitution-risk exposure and adjustment vulnerability using a worker-weighted geometric structure:

$$
\mathrm{FEALR}^{\mathrm{core}}_{q,r,t} =
100
\sum_{o,i}
W_{q,o,i,r,t}
\sqrt{
S_{o,t}
V_{q,o,r,t}
},
$$

where $W_{q,o,i,r,t}$ is the worker share for income quintile $q$, occupation $o$, industry $i$, geography $r$, and period $t$, with $\sum_{o,i}W_{q,o,i,r,t}=1$; $S_{o,t}$ is normalized substitution-risk exposure; and $V_{q,o,r,t}$ is normalized adjustment vulnerability, including relevant worker and local-labor-market constraints. The geometric interaction makes high core risk depend on both meaningful substitution exposure and limited capacity to adjust. Adoption pressure remains a separate overlay because technical exposure and realized deployment are different stages of the pathway.

Proposed public outputs include raw exposure, substitution-risk exposure, adjustment capacity and its transformed vulnerability term, core risk, and adoption-pressure-adjusted risk, reported by income fifth and geography.

The measure should not be described as a probability of job loss. Occupational exposure, technological capability, firm adoption, labor demand, institutional response, and worker adaptation are different stages of the pathway from technical possibility to realized displacement.

As of this note, the AI Labor Risk Index remains developmental and has its own acquisition-harness and specification work. It is not part of the operational DMI monthly series.

### 11.3 Why the applications remain separate

The common framework asks how a broad social or economic condition differs across income fifths. It does not require every application to share a formula. Economic misery, healthcare burden, and AI labor risk have different causal structures and validation targets.

Maintaining separate constructs prevents “Five Economies” from becoming an undifferentiated composite index and preserves the interpretability of each application.

---

## 12. Limitations

The principal limitations of the current DMI include:

1. **Expenditure-share uncertainty.** Consumer Expenditure Surveys estimates are subject to sampling and measurement error, especially at detailed category-by-group resolution.
2. **Weight lags.** Group expenditure patterns are observed with a lag and may change during shocks.
3. **Category concordance.** Consumer expenditure categories and CPI item categories do not map perfectly.
4. **Within-quintile heterogeneity.** Five groups suppress meaningful variation within each fifth.
5. **Shared slack within groups.** The current labor component does not capture quintile-specific unemployment or underemployment risk; all released cross-quintile differentiation comes from the price component.
6. **Current geographic scope.** Public releases are national only. A future state extension would necessarily depend partly on broader geographic price series and declared proxies and must be separately implemented and validated before release.
7. **Core implementation status.** Core is an intended specification, not a current operational output. The existing eight-category basket cannot isolate all relevant energy components; implementation requires a finer CPI–Consumer Expenditure mapping and separate validation before any result is released under the Core label.
8. **Index-number choices.** CPI and PCE differ in population, scope, weights, formulas, and treatment of expenditures made on behalf of households.
9. **Revisions and breaks.** Source series, survey designs, and seasonal-adjustment procedures can change.
10. **Summary compression.** DMI Median, DMI Stress, Income Pressure Spread, and Income Pressure Tilt can conceal the five-value profile and its component mix.
11. **No direct hardship measurement.** DMI estimates economic pressure; hardship must be evaluated with separate outcome data.

These limitations support a restrained interpretation: **directional insight and distributional visibility, not decimal-point precision**.

---

## 13. Research and implementation priorities

The next stage should emphasize evidence and reliability rather than adding many components.

### Near-term priorities

1. Maintain stable methods documentation for Baseline and Slack-Plus, and complete the finer-grained CPI–Consumer Expenditure mapping, data acquisition, and validation design required before Core can be implemented.
2. Complete a lightweight validation panel using independent hardship measures.
3. Compare CPI-based quintile inflation with BEA’s income-stratified PCE series.
4. Strengthen cross-file and summary-metric quality checks in the monthly release process.
5. Design, implement, and validate a separately specified state extension, including its exact geographic proxy hierarchy, before publishing state estimates or rankings.
6. Publish component contributions so users can see why quintiles differ.

### Medium-term research

1. Back-test the DMI across inflationary, recessionary, and recovery regimes.
2. Test whether Slack-Plus adds explanatory or predictive value relative to Baseline.
3. Evaluate alternative category mappings and expenditure-weight vintages.
4. Explore a research DMI-PCE specification.
5. Assess whether an Essentials Pressure view adds information without becoming normative or redundant.
6. Compare alternative group-specific labor-slack research methods: an education-to-income proxy with an explicit crosswalk, direct CPS microdata estimation, and occupational or industry weighting.

### Conditional expansion

More extensive replication archives, permanent release identifiers, state and finer geographies, and additional companion indexes should be developed in proportion to demonstrated external use and the project’s ability to maintain them reliably.

---

## 14. Conclusion

The Distributional Misery Index begins with a simple observation: one economy can produce several materially different economic experiences. Aggregate indicators remain essential, but they should not be mistaken for complete descriptions of household conditions.

The DMI retains the communicative strength of the classic Misery Index while making its components more explicit and its inflation signal distribution-aware. The operational Baseline and Slack-Plus specifications make clear that labor-market slack is a choice that should be declared rather than hidden. The intended Core specification would extend that discipline to inflation scope once the finer-grained data architecture required for a defensible food-and-energy exclusion has been implemented and validated. The distinction among DMI Median, DMI Stress, Income Pressure Spread, and Income Pressure Tilt likewise prevents one compressed statistic from carrying incompatible meanings. The monthly release architecture turns the concept into a reproducible public process instead of a one-time calculation.

New official distributional measures—especially BEA’s income-stratified PCE price index—make the research environment stronger and the standard of evidence higher. They also reinforce the proper stance of the project: distributional differences must be measured, compared, and sometimes found to be small. The Five Economies framework is valuable not because it guarantees a dramatic result, but because it refuses to let an average answer a distributional question by default.

The DMI’s intended contribution is therefore one of disciplined visibility: making national economic pressure across income groups easier to observe, test, critique, and discuss, while keeping proposed geographic extensions clearly separated from implemented public results.

---

## References

Bureau of Economic Analysis. “Distribution of U.S. Personal Income,” including the Income-Stratified Personal Consumption Expenditures Price Index. Updated July 17, 2026. <https://www.bea.gov/data/special-topics/distribution-of-personal-income>. Accessed August 10, 2026.

Bureau of Economic Analysis. “Innovations in Distribution of Income Statistics: New Data and New Tool.” June 16, 2026. <https://www.bea.gov/news/blog/2026-06-16/innovations-distribution-income-statistics-new-data-and-new-tool>. Accessed August 10, 2026.

Bureau of Labor Statistics. “Consumer Price Index.” <https://www.bls.gov/cpi/>. Accessed August 10, 2026.

Bureau of Labor Statistics. “Consumer Expenditure Surveys Tables.” <https://www.bls.gov/cex/tables.htm>. Accessed August 10, 2026.

Bureau of Labor Statistics. “Labor Force Characteristics: Alternative Measures of Labor Underutilization (U-1 through U-6).” <https://www.bls.gov/cps/lfcharacteristics.htm>. Accessed August 10, 2026.

Bureau of Labor Statistics. “The Employment Situation — June 2026,” including Table A-4, “Employment Status of the Civilian Population 25 Years and Over by Educational Attainment.” Released July 2, 2026. <https://www.bls.gov/news.release/archives/empsit_07022026.htm>. Accessed August 10, 2026.

Bureau of Labor Statistics. “Local Area Unemployment Statistics.” <https://www.bls.gov/lau/>. Accessed August 10, 2026.

Blanchflower, David G., David N. F. Bell, Alberto Montagnoli, and Mirko Moro. “The Happiness Trade-Off between Unemployment and Inflation.” *Journal of Money, Credit and Banking* 46, supplement 2 (2014): 117–141. <https://doi.org/10.1111/jmcb.12154>

Chetty, Raj, Matthew O. Jackson, Theresa Kuchler, Johannes Stroebel, et al. “Social Capital I: Measurement and Associations with Economic Mobility.” *Nature* 608 (2022): 108–121. <https://opportunityinsights.org/paper/social-capital-i-measurement-and-associations-with-economic-mobility/>. Accessed August 10, 2026.

Chetty, Raj, Nathaniel Hendren, Patrick Kline, and Emmanuel Saez. “Where Is the Land of Opportunity? The Geography of Intergenerational Mobility in the United States.” *Quarterly Journal of Economics* 129, no. 4 (2014): 1553–1623. <https://opportunityinsights.org/paper/land-of-opportunity/>. Accessed August 10, 2026.

Di Tella, Rafael, Robert J. MacCulloch, and Andrew J. Oswald. “Preferences over Inflation and Unemployment: Evidence from Surveys of Happiness.” *American Economic Review* 91, no. 1 (2001): 335–341. <https://doi.org/10.1257/aer.91.1.335>

Dunn, Megan. “The Current Population Survey—Tracking Unemployment in the United States for over 75 Years.” *Monthly Labor Review*, January 2018. <https://www.bls.gov/opub/mlr/2018/article/the-current-population-survey-tracking-unemployment.htm>. Accessed August 10, 2026.

Gindelsky, Marina, and Robert Martin. “Rethinking Inflation Inequality: Evidence from National Accounts.” *Macroeconomic Dynamics* 30 (2026): e26. <https://doi.org/10.1017/S1365100526100984>

Gindelsky, Marina, and Robert Martin. “Rethinking Inflation Heterogeneity: Evidence from National Accounts.” BEA Working Paper 2025-9. <https://www.bea.gov/system/files/papers/BEA-WP2025-9.pdf>. Accessed August 10, 2026.

Klick, Josh. “Examining U.S. Inflation across Households Grouped by Equivalized Income.” *Monthly Labor Review*, 2024. <https://www.bls.gov/opub/mlr/2024/article/examining-us-inflation-across-households-grouped-by-equivalized-income.htm>. Accessed August 10, 2026.

Klick, Josh, and Anya Stockburger. “Experimental CPI for Lower and Higher Income Households.” BLS Working Paper 537, 2021. <https://www.bls.gov/osmr/research-papers/2021/pdf/ec210030.pdf>. Accessed August 10, 2026.

Lovell, Michael C., and Pao-Lin Tien. “Economic Discomfort and Consumer Sentiment.” *Eastern Economic Journal* 26, no. 1 (2000): 1–8. <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=222510>

Office for National Statistics. “Household Costs Indices for UK Household Groups: Quality and Methodology Information.” Updated May 28, 2026. <https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/householdcostsindicesforukhouseholdgroupsqmi>. Accessed August 10, 2026.

U.S. Census Bureau. “Household Trends and Outlook Pulse Survey (HTOPS).” Updated May 6, 2026. <https://www.census.gov/programs-surveys/htops.html>. Accessed August 10, 2026.

---

## Attribution and AI-use disclosure

The particular synthesis of the **Five Economies** framework, **By Fifths analysis**, and the **Distributional Misery Index** presented in this note was initiated and directed by Thomas C. Williams. The work builds on the classic Misery Index, official price and labor-market statistics, distributional-inflation research, and other antecedent concepts and methods credited in the text and references. No claim is made to have originated those antecedents.

This paper was developed with assistance from OpenAI’s ChatGPT and Anthropic’s Claude for exploratory analysis, research synthesis, source discovery and review, structural development, drafting and editing, methodological critique, consistency checking, and document production. Thomas C. Williams supplied the core concepts and project materials, directed the work, made the methodological and editorial decisions, selected which AI-generated suggestions to incorporate, reviewed the claims and cited sources, and accepts sole responsibility for the final content and any errors. The AI systems are not authors, and their outputs were treated as proposals rather than sources of authority.

© 2026 Thomas C. Williams. Licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0).


*Document version: v0.4.6*
*This concept note is descriptive and does not constitute financial, investment, legal, or policy advice.*
