from __future__ import annotations

import argparse
import math
import random
from collections import Counter
from pathlib import Path

from common import load_json, now_iso, project_path, save_json

SCHEMA_VERSION = 5


def load_licenses() -> list[dict]:
    licenses_path = project_path("data", "raw", "LICENSES.json")
    data = load_json(licenses_path)
    return data if isinstance(data, list) else []


def filter_licenses_for_levels(licenses: list[dict]) -> list[dict]:
    return [
        {"name": item["name"], "url": item["url"], "license": item["license"]}
        for item in licenses
        if item["id"] in ("re-enable", "wikipedia", "wordfreq")
    ]


# Fields that are only needed at build time, not runtime
BUILD_ONLY_LEVEL_FIELDS = frozenset(
    {
        "seed",
        "layoutMode",
        "placementStats",
        "difficulty",
        "difficultyTier",
        "difficultyFeatures",
        "minAnswerFreq",
        "avgAnswerFreq",
        "p25AnswerFreq",
        "wheelSize",
        "wheelShape",
        "campaignIndex",
        "combos",
    }
)
BUILD_ONLY_ANSWER_FIELDS = frozenset({"freq", "tokenCount"})
BUILD_ONLY_GROUP_FIELDS = frozenset(
    {
        "runId",
        "runIds",
        "targetSize",
        "targetAvgAnswerFreq",
        "shapeTargets",
        "shapeCounts",
        "frequencyFloor",
        "effectiveFrequencyFloor",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export scored levels for frontend consumption."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Grouped export manifest from generate_all.py.",
    )
    parser.add_argument(
        "--bundle-out",
        default=str(project_path("data", "generated", "levels.bundle.json")),
        help="Output path for full metadata bundle (used by analysis tools).",
    )
    parser.add_argument(
        "--split-dir",
        default=str(project_path("src", "data")),
        help="Directory for trimmed split files (levels._meta.json, levels.*.json).",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def trim_answer_for_production(answer: dict) -> dict:
    """Remove build-only fields from an answer object."""
    return {
        key: value
        for key, value in answer.items()
        if key not in BUILD_ONLY_ANSWER_FIELDS
    }


def trim_level_for_production(level: dict) -> dict:
    """Remove build-only fields from a level object for runtime use."""
    trimmed = {
        key: value for key, value in level.items() if key not in BUILD_ONLY_LEVEL_FIELDS
    }
    if "answers" in trimmed:
        trimmed["answers"] = [
            trim_answer_for_production(ans) if isinstance(ans, dict) else ans
            for ans in trimmed["answers"]
        ]
    return trimmed


def trim_group_for_production(group: dict) -> dict:
    """Remove build-only fields from a group definition for runtime use."""
    trimmed = {
        key: value for key, value in group.items() if key not in BUILD_ONLY_GROUP_FIELDS
    }
    return trimmed


def level_freq_stats(level: dict) -> tuple[float, float, float]:
    min_freq = float(level.get("minAnswerFreq", 0.0))
    avg_freq = float(level.get("avgAnswerFreq", 0.0))
    p25_freq = float(level.get("p25AnswerFreq", 0.0))
    if min_freq > 0 or avg_freq > 0 or p25_freq > 0:
        return min_freq, avg_freq, p25_freq

    answer_freqs = sorted(
        float(item.get("freq", 0.0)) for item in level.get("answers", [])
    )
    if not answer_freqs:
        return 0.0, 0.0, 0.0
    avg = sum(answer_freqs) / len(answer_freqs)
    p25_index = max(0, min(len(answer_freqs) - 1, int((len(answer_freqs) - 1) * 0.25)))
    return answer_freqs[0], avg, answer_freqs[p25_index]


def frequency_rank_key(level: dict) -> tuple:
    min_freq, avg_freq, p25_freq = level_freq_stats(level)
    level_id = str(level.get("id", ""))
    group = ""
    index = 0
    for ch in level_id:
        if ch.isalpha():
            group += ch
        else:
            break
    suffix = level_id[len(group) :]
    if suffix.isdigit():
        index = int(suffix)
    return (
        -round(min_freq, 6),
        -round(avg_freq, 6),
        -round(p25_freq, 6),
        round(float(level.get("difficulty", 1.0)), 6),
        group,
        index,
        str(level.get("seed", "")),
    )


def wheel_letter_bag_key(level: dict) -> str:
    wheel_tokens = [str(token) for token in level.get("letterWheel", [])]
    letter_bag = "".join(wheel_tokens)
    if letter_bag:
        return "".join(sorted(letter_bag))
    return "|".join(sorted(wheel_tokens))


def wheel_shape_id(level: dict) -> str:
    wheel_tokens = [str(token) for token in level.get("letterWheel", [])]
    singles = sum(1 for token in wheel_tokens if len(token) == 1)
    doubles = sum(1 for token in wheel_tokens if len(token) == 2)
    triples = sum(1 for token in wheel_tokens if len(token) == 3)
    return f"{singles}/{doubles}/{triples}"


def shuffle_levels_with_shape_constraint(
    levels: list[dict],
    rng: random.Random,
) -> list[dict]:
    """Shuffle levels while avoiding consecutive same wheel shapes.

    Uses weighted random selection: shapes with more remaining levels
    have higher selection probability, while still avoiding consecutive
    same shapes when possible.
    """
    if len(levels) <= 1:
        return levels[:]

    shapes = [wheel_shape_id(level) for level in levels]

    by_shape: dict[str, list[int]] = {}
    for idx, shape in enumerate(shapes):
        by_shape.setdefault(shape, []).append(idx)

    for indices in by_shape.values():
        rng.shuffle(indices)

    shape_queue: dict[str, int] = {shape: 0 for shape in by_shape}
    result_indices: list[int] = []
    last_shape: str | None = None

    def remaining(shape: str) -> int:
        return len(by_shape[shape]) - shape_queue[shape]

    for _ in range(len(levels)):
        available = [s for s in by_shape if remaining(s) > 0 and s != last_shape]

        if not available:
            available = [s for s in by_shape if remaining(s) > 0]

        weights = [remaining(s) ** 2 for s in available]
        total = sum(weights)
        r = rng.random() * total
        cumulative = 0
        chosen = available[0]
        for s, w in zip(available, weights):
            cumulative += w
            if r <= cumulative:
                chosen = s
                break

        queue_pos = shape_queue[chosen]
        result_indices.append(by_shape[chosen][queue_pos])
        shape_queue[chosen] = queue_pos + 1
        last_shape = chosen

    return [levels[i] for i in result_indices]


def answer_text_set(level: dict) -> set[str]:
    return {
        str(answer.get("text", ""))
        for answer in level.get("answers", [])
        if isinstance(answer, dict) and str(answer.get("text", ""))
    }


def overlap_penalty(
    answer_words: set[str],
    recent_answer_sets: list[set[str]],
    overlap_window: int,
) -> int:
    if overlap_window <= 0 or not answer_words or not recent_answer_sets:
        return 0
    return sum(
        len(answer_words.intersection(previous_answers))
        for previous_answers in recent_answer_sets[-overlap_window:]
    )


def cooldown_penalty(
    answer_words: set[str],
    word_last_seen: dict[str, int],
    campaign_index: int,
    cooldown_levels: int,
    short_word_len_max: int,
    short_word_cooldown_levels: int,
) -> int:
    if cooldown_levels <= 0 or not answer_words:
        return 0
    penalty = 0
    for word in answer_words:
        effective_cooldown = cooldown_levels
        if len(word) <= short_word_len_max:
            effective_cooldown = max(effective_cooldown, short_word_cooldown_levels)
        last_seen = word_last_seen.get(word)
        if last_seen is None:
            continue
        distance = campaign_index - last_seen
        if distance < effective_cooldown:
            penalty += effective_cooldown - distance
    return penalty


def short_word_signatures(answer_words: set[str], short_word_len_max: int) -> set[str]:
    return {
        "".join(sorted(word))
        for word in answer_words
        if 3 <= len(word) <= short_word_len_max
    }


def three_letter_reverse_signatures(answer_words: set[str]) -> set[str]:
    signatures: set[str] = set()
    for word in answer_words:
        if len(word) != 3:
            continue
        reverse = word[::-1]
        signatures.add(word if word <= reverse else reverse)
    return signatures


def short_word_signature_penalty(
    signatures: set[str],
    signature_last_seen: dict[str, int],
    campaign_index: int,
    signature_cooldown_levels: int,
    signature_penalty_weight: float,
) -> float:
    if (
        signature_cooldown_levels <= 0
        or signature_penalty_weight <= 0
        or not signatures
    ):
        return 0.0

    penalty = 0.0
    for signature in signatures:
        last_seen = signature_last_seen.get(signature)
        if last_seen is None:
            continue
        distance = campaign_index - last_seen
        if distance < signature_cooldown_levels:
            penalty += (signature_cooldown_levels - distance) * signature_penalty_weight
    return round(penalty, 6)


def exceeds_recent_overlap_limit(
    answer_words: set[str],
    recent_answer_sets: list[set[str]],
    overlap_window: int,
    max_shared_words: int,
) -> bool:
    if (
        overlap_window <= 0
        or max_shared_words < 0
        or not answer_words
        or not recent_answer_sets
    ):
        return False
    for previous_answers in recent_answer_sets[-overlap_window:]:
        if len(answer_words.intersection(previous_answers)) > max_shared_words:
            return True
    return False


def normalize_scored_levels(payload: dict) -> list[dict]:
    levels = [item for item in payload.get("levels", []) if isinstance(item, dict)]
    levels.sort(key=frequency_rank_key)
    return levels


def exceeds_cross_pack_word_reuse_cap(
    answer_words: set[str],
    word_group_counts: dict[str, int],
    current_group_words: set[str],
    short_word_len_max: int,
    short_word_max_group_reuse: int,
    long_word_max_group_reuse: int,
) -> bool:
    if (
        not answer_words
        or short_word_max_group_reuse < 0
        or long_word_max_group_reuse < 0
    ):
        return False
    for word in answer_words:
        max_reuse = (
            short_word_max_group_reuse
            if len(word) <= short_word_len_max
            else long_word_max_group_reuse
        )
        projected_groups = word_group_counts.get(word, 0)
        if word not in current_group_words:
            projected_groups += 1
        if projected_groups > max_reuse:
            return True
    return False


def exceeds_three_letter_signature_reuse_cap(
    signatures: set[str],
    signature_group_counts: dict[str, int],
    current_group_signatures: set[str],
    max_group_reuse: int,
) -> bool:
    if not signatures or max_group_reuse < 1:
        return False
    for signature in signatures:
        projected_groups = signature_group_counts.get(signature, 0)
        if signature not in current_group_signatures:
            projected_groups += 1
        if projected_groups > max_group_reuse:
            return True
    return False


def global_word_overuse_penalty(
    answer_words: set[str],
    word_group_counts: dict[str, int],
    current_group_words: set[str],
    short_word_len_max: int,
    short_word_weight: float,
    long_word_weight: float,
) -> float:
    if not answer_words or (short_word_weight <= 0 and long_word_weight <= 0):
        return 0.0
    penalty = 0.0
    for word in answer_words:
        seen_count = word_group_counts.get(word, 0)
        if word not in current_group_words:
            seen_count += 1
        if seen_count <= 1:
            continue
        weight = (
            short_word_weight if len(word) <= short_word_len_max else long_word_weight
        )
        if weight <= 0:
            continue
        penalty += weight * math.sqrt(seen_count - 1)
    return round(penalty, 6)


def profile_target_avg_freq(
    group_index: int,
    profile_start_group: int,
    profile_end_group: int,
    target_start: float,
    target_end: float,
    target_power: float,
) -> float | None:
    if group_index < profile_start_group or profile_end_group <= profile_start_group:
        return None
    clamped_index = max(profile_start_group, min(group_index, profile_end_group))
    progress = (clamped_index - profile_start_group) / (
        profile_end_group - profile_start_group
    )
    shaped_progress = progress**target_power
    return target_start + ((target_end - target_start) * shaped_progress)


def profile_distance_penalty(
    candidate_avg_freq: float,
    target_avg_freq: float | None,
    target_weight: float,
) -> float:
    if target_avg_freq is None or target_weight <= 0:
        return 0.0
    return round(abs(candidate_avg_freq - target_avg_freq) * target_weight, 6)


def min_required_group_size(target_size: int, undershoot_ratio: float) -> int:
    if target_size <= 0:
        return 0
    if undershoot_ratio <= 0:
        return target_size
    ratio = min(max(undershoot_ratio, 0.0), 0.999999)
    return max(0, min(target_size, int(math.ceil(target_size * (1.0 - ratio)))))


def select_group_levels(
    pool: list[dict],
    target_size: int,
    min_required_size: int,
    context_label: str,
    freq_floor: float | None,
    relax_step: float,
    relax_max_steps: int,
    global_seen_wheels: set[str],
    recent_answer_sets: list[set[str]],
    word_last_seen: dict[str, int],
    next_campaign_index: int,
    overlap_window: int,
    strict_novelty_filters: bool,
    word_cooldown_levels: int,
    short_word_len_max: int,
    short_word_cooldown_levels: int,
    short_word_signature_last_seen: dict[str, int],
    short_word_signature_cooldown_levels: int,
    short_word_signature_penalty_weight: float,
    hard_overlap_window: int,
    hard_overlap_max_shared_words: int,
    prior_group_answers: set[str],
    max_prior_group_reuse_answers: int,
    prior_group_word_counts: dict[str, int],
    global_overuse_short_word_len_max: int,
    global_overuse_short_weight: float,
    global_overuse_long_weight: float,
    target_avg_freq: float | None,
    target_avg_freq_weight: float,
    min_avg_freq_floor: float | None,
    max_avg_freq_ceiling: float | None,
    enforce_cross_pack_word_caps: bool,
    cross_pack_short_word_len_max: int,
    cross_pack_short_word_max_group_reuse: int,
    cross_pack_long_word_max_group_reuse: int,
    enforce_three_letter_signature_reuse_cap: bool,
    three_letter_signature_group_counts: dict[str, int],
    three_letter_signature_max_group_reuse: int,
) -> tuple[list[dict], float | None]:
    if target_size <= 0:
        return [], freq_floor
    required_size = max(0, min(min_required_size, target_size))
    available_indices: list[int] = []
    available_seen = set(global_seen_wheels)
    for idx, level in enumerate(pool):
        wheel_key = wheel_letter_bag_key(level)
        if wheel_key in available_seen:
            continue
        available_seen.add(wheel_key)
        available_indices.append(idx)

    if len(available_indices) < required_size:
        raise SystemExit(
            (
                "Not enough globally-unique wheel levels to fill group"
                f" ({context_label})"
                f" (need >= {required_size}/{target_size}, have {len(available_indices)})."
            )
        )

    selected_candidate_indices: list[int] = []
    effective_floor = freq_floor

    eligible_indices: list[int] = []
    if freq_floor is None:
        eligible_indices = available_indices
    else:
        for step in range(max(0, relax_max_steps) + 1):
            current_floor = freq_floor - (step * max(0.0, relax_step))
            matching = [
                idx
                for idx in available_indices
                if level_freq_stats(pool[idx])[0] >= current_floor
            ]
            if len(matching) >= target_size:
                eligible_indices = matching
                effective_floor = current_floor
                break

    if not eligible_indices:
        eligible_indices = available_indices

    local_recent_answer_sets = list(recent_answer_sets)
    local_word_last_seen = dict(word_last_seen)
    local_short_word_signature_last_seen = dict(short_word_signature_last_seen)
    local_prior_group_word_counts = dict(prior_group_word_counts)
    local_three_letter_signature_group_counts = dict(
        three_letter_signature_group_counts
    )
    local_current_group_words: set[str] = set()
    local_current_group_three_letter_signatures: set[str] = set()
    answer_sets_by_index = {idx: answer_text_set(pool[idx]) for idx in eligible_indices}
    short_word_signatures_by_index = {
        idx: short_word_signatures(answer_sets_by_index[idx], short_word_len_max)
        for idx in eligible_indices
    }
    three_letter_signatures_by_index = {
        idx: three_letter_reverse_signatures(answer_sets_by_index[idx])
        for idx in eligible_indices
    }
    avg_freq_by_index = {
        idx: level_freq_stats(pool[idx])[1] for idx in eligible_indices
    }
    local_prior_group_reuse_answers = 0
    remaining = set(eligible_indices)
    for offset in range(target_size):
        campaign_index = next_campaign_index + offset
        slots_left = target_size - len(selected_candidate_indices)
        candidate_indices = list(remaining)

        if hard_overlap_window > 0 and hard_overlap_max_shared_words >= 0:
            strict_overlap_indices = [
                idx
                for idx in candidate_indices
                if not exceeds_recent_overlap_limit(
                    answer_sets_by_index[idx],
                    local_recent_answer_sets,
                    hard_overlap_window,
                    hard_overlap_max_shared_words,
                )
            ]
            if len(strict_overlap_indices) >= slots_left:
                candidate_indices = strict_overlap_indices

        if prior_group_answers and max_prior_group_reuse_answers >= 0:
            strict_group_reuse_indices = [
                idx
                for idx in candidate_indices
                if local_prior_group_reuse_answers
                + len(answer_sets_by_index[idx].intersection(prior_group_answers))
                <= max_prior_group_reuse_answers
            ]
            if strict_novelty_filters or len(strict_group_reuse_indices) >= slots_left:
                candidate_indices = strict_group_reuse_indices

        if min_avg_freq_floor is not None or max_avg_freq_ceiling is not None:
            strict_profile_band_indices = [
                idx
                for idx in candidate_indices
                if (
                    (
                        min_avg_freq_floor is None
                        or avg_freq_by_index[idx] >= min_avg_freq_floor
                    )
                    and (
                        max_avg_freq_ceiling is None
                        or avg_freq_by_index[idx] <= max_avg_freq_ceiling
                    )
                )
            ]
            if len(strict_profile_band_indices) >= slots_left:
                candidate_indices = strict_profile_band_indices
            else:
                if min_avg_freq_floor is not None:
                    strict_profile_floor_indices = [
                        idx
                        for idx in candidate_indices
                        if avg_freq_by_index[idx] >= min_avg_freq_floor
                    ]
                    if len(strict_profile_floor_indices) >= slots_left:
                        candidate_indices = strict_profile_floor_indices

                if max_avg_freq_ceiling is not None:
                    strict_profile_ceiling_indices = [
                        idx
                        for idx in candidate_indices
                        if avg_freq_by_index[idx] <= max_avg_freq_ceiling
                    ]
                    if len(strict_profile_ceiling_indices) >= slots_left:
                        candidate_indices = strict_profile_ceiling_indices

        if enforce_cross_pack_word_caps:
            strict_cross_pack_indices = [
                idx
                for idx in candidate_indices
                if not exceeds_cross_pack_word_reuse_cap(
                    answer_sets_by_index[idx],
                    local_prior_group_word_counts,
                    local_current_group_words,
                    cross_pack_short_word_len_max,
                    cross_pack_short_word_max_group_reuse,
                    cross_pack_long_word_max_group_reuse,
                )
            ]
            if strict_novelty_filters or len(strict_cross_pack_indices) >= slots_left:
                candidate_indices = strict_cross_pack_indices

        if enforce_three_letter_signature_reuse_cap:
            strict_three_letter_signature_indices = [
                idx
                for idx in candidate_indices
                if not exceeds_three_letter_signature_reuse_cap(
                    three_letter_signatures_by_index[idx],
                    local_three_letter_signature_group_counts,
                    local_current_group_three_letter_signatures,
                    three_letter_signature_max_group_reuse,
                )
            ]
            if (
                strict_novelty_filters
                or len(strict_three_letter_signature_indices) >= slots_left
            ):
                candidate_indices = strict_three_letter_signature_indices

        best_index = -1
        best_key: tuple | None = None
        for idx in candidate_indices:
            level = pool[idx]
            answer_words = answer_sets_by_index[idx]
            novelty_key = (
                cooldown_penalty(
                    answer_words,
                    local_word_last_seen,
                    campaign_index,
                    word_cooldown_levels,
                    short_word_len_max,
                    short_word_cooldown_levels,
                ),
                short_word_signature_penalty(
                    short_word_signatures_by_index[idx],
                    local_short_word_signature_last_seen,
                    campaign_index,
                    short_word_signature_cooldown_levels,
                    short_word_signature_penalty_weight,
                ),
                overlap_penalty(
                    answer_words,
                    local_recent_answer_sets,
                    overlap_window,
                ),
                global_word_overuse_penalty(
                    answer_words,
                    local_prior_group_word_counts,
                    local_current_group_words,
                    global_overuse_short_word_len_max,
                    global_overuse_short_weight,
                    global_overuse_long_weight,
                ),
                len(answer_words.intersection(prior_group_answers)),
                profile_distance_penalty(
                    avg_freq_by_index[idx],
                    target_avg_freq,
                    target_avg_freq_weight,
                ),
            )
            rank_key = novelty_key + frequency_rank_key(level)
            if best_key is None or rank_key < best_key:
                best_key = rank_key
                best_index = idx

        if best_index < 0:
            break
        selected_candidate_indices.append(best_index)
        remaining.remove(best_index)
        selected_answers = answer_sets_by_index[best_index]
        if prior_group_answers and max_prior_group_reuse_answers >= 0:
            local_prior_group_reuse_answers += len(
                selected_answers.intersection(prior_group_answers)
            )
        local_recent_answer_sets.append(selected_answers)
        for word in selected_answers:
            if word in local_current_group_words:
                continue
            local_current_group_words.add(word)
            local_prior_group_word_counts[word] = (
                local_prior_group_word_counts.get(word, 0) + 1
            )
        for word in selected_answers:
            local_word_last_seen[word] = campaign_index
        for signature in short_word_signatures_by_index[best_index]:
            local_short_word_signature_last_seen[signature] = campaign_index
        for signature in three_letter_signatures_by_index[best_index]:
            if signature in local_current_group_three_letter_signatures:
                continue
            local_current_group_three_letter_signatures.add(signature)
            local_three_letter_signature_group_counts[signature] = (
                local_three_letter_signature_group_counts.get(signature, 0) + 1
            )

    if len(selected_candidate_indices) < required_size:
        raise SystemExit(
            (
                "Unable to fill group with novelty constraints"
                f" ({context_label})"
                f" (need >= {required_size}/{target_size}, have {len(selected_candidate_indices)})."
            )
        )

    selected = [pool[idx] for idx in selected_candidate_indices]
    recent_answer_sets[:] = local_recent_answer_sets
    word_last_seen.clear()
    word_last_seen.update(local_word_last_seen)
    short_word_signature_last_seen.clear()
    short_word_signature_last_seen.update(local_short_word_signature_last_seen)
    prior_group_word_counts.clear()
    prior_group_word_counts.update(local_prior_group_word_counts)
    three_letter_signature_group_counts.clear()
    three_letter_signature_group_counts.update(
        local_three_letter_signature_group_counts
    )
    for level in selected:
        global_seen_wheels.add(wheel_letter_bag_key(level))
    for idx in sorted(selected_candidate_indices, reverse=True):
        pool.pop(idx)
    return selected, effective_floor


def remove_selected_levels_from_run_pools(
    run_pools: dict[str, list[dict]],
    run_ids: list[str],
    selected_levels: list[dict],
) -> None:
    if not selected_levels:
        return
    selected_object_ids = {id(level) for level in selected_levels}
    for run_id in run_ids:
        pool = run_pools.get(run_id)
        if pool is None:
            continue
        run_pools[run_id] = [
            level for level in pool if id(level) not in selected_object_ids
        ]


def grouped_export(
    args: argparse.Namespace,
) -> tuple[list[dict], list[dict], Path, dict, dict[str, str]]:
    manifest_path = resolve_path(args.manifest)
    manifest = load_json(manifest_path)
    runs = manifest.get("runs", [])
    groups = manifest.get("groups", [])
    group_plan = manifest.get("groupPlan", {})
    relax_step = float(group_plan.get("frequencyRelaxStep", 0.0))
    relax_steps = int(group_plan.get("frequencyRelaxMaxSteps", 0))
    overlap_window = max(0, int(group_plan.get("noveltyOverlapWindow", 12)))
    default_word_cooldown = max(0, int(group_plan.get("wordCooldownLevels", 5)))
    early_group_count = max(0, int(group_plan.get("wordCooldownEarlyGroups", 3)))
    strict_novelty_early_groups = max(
        0, int(group_plan.get("strictNoveltyEarlyGroups", 0))
    )
    group_size_undershoot_ratio = float(group_plan.get("groupSizeUndershootRatio", 0.0))
    early_word_cooldown = max(0, int(group_plan.get("wordCooldownEarlyLevels", 16)))
    short_word_len_max = max(1, int(group_plan.get("shortWordLenMax", 4)))
    default_short_word_cooldown = max(
        0, int(group_plan.get("shortWordCooldownLevels", 6))
    )
    early_short_word_cooldown = max(
        0, int(group_plan.get("shortWordCooldownEarlyLevels", 16))
    )
    default_short_word_signature_cooldown = max(
        0, int(group_plan.get("shortWordSignatureCooldownLevels", 10))
    )
    early_short_word_signature_cooldown = max(
        0, int(group_plan.get("shortWordSignatureCooldownEarlyLevels", 20))
    )
    short_word_signature_penalty_weight = max(
        0.0, float(group_plan.get("shortWordSignaturePenaltyWeight", 2.0))
    )
    hard_overlap_window = max(0, int(group_plan.get("hardOverlapWindow", 16)))
    hard_overlap_max_shared_words = int(group_plan.get("hardOverlapMaxSharedWords", 2))
    cross_pack_early_group_count = max(
        0, int(group_plan.get("crossPackEarlyGroups", 5))
    )
    cross_pack_short_word_len_max = max(
        1, int(group_plan.get("crossPackShortWordLenMax", short_word_len_max))
    )
    cross_pack_short_word_max_group_reuse = max(
        0, int(group_plan.get("crossPackShortWordMaxGroupReuse", 1))
    )
    cross_pack_long_word_max_group_reuse = max(
        0, int(group_plan.get("crossPackLongWordMaxGroupReuse", 2))
    )
    cross_pack_late_start_group = max(
        0,
        int(group_plan.get("crossPackLateStartGroup", cross_pack_early_group_count)),
    )
    cross_pack_late_short_word_max_group_reuse = max(
        0,
        int(group_plan.get("crossPackLateShortWordMaxGroupReuse", 12)),
    )
    cross_pack_late_long_word_max_group_reuse = max(
        0,
        int(group_plan.get("crossPackLateLongWordMaxGroupReuse", 16)),
    )
    three_letter_signature_early_group_count = max(
        0, int(group_plan.get("threeLetterSignatureEarlyGroups", 0))
    )
    three_letter_signature_max_group_reuse = max(
        1, int(group_plan.get("threeLetterSignatureMaxGroupReuse", 2))
    )
    global_overuse_short_word_len_max = max(
        1, int(group_plan.get("globalOveruseShortWordLenMax", short_word_len_max))
    )
    global_overuse_short_weight = max(
        0.0, float(group_plan.get("globalOveruseShortWeight", 0.45))
    )
    global_overuse_long_weight = max(
        0.0, float(group_plan.get("globalOveruseLongWeight", 0.12))
    )
    difficulty_profile_start_group = max(
        0, int(group_plan.get("difficultyProfileStartGroup", 4))
    )
    difficulty_target_avg_freq_start = float(
        group_plan.get("difficultyTargetAvgFreqStart", 4.05)
    )
    difficulty_target_avg_freq_end = float(
        group_plan.get("difficultyTargetAvgFreqEnd", 3.70)
    )
    difficulty_target_power = max(
        0.0001, float(group_plan.get("difficultyTargetPower", 1.4))
    )
    difficulty_target_weight = max(
        0.0, float(group_plan.get("difficultyTargetWeight", 3.5))
    )
    difficulty_floor_margin = max(
        0.0, float(group_plan.get("difficultyFloorMargin", 0.45))
    )
    difficulty_ceiling_margin = max(
        0.0, float(group_plan.get("difficultyCeilingMargin", 0.20))
    )
    group_reuse_budget_ratio = max(
        0.0, float(group_plan.get("groupReuseBudgetRatio", 0.2))
    )
    group_reuse_budget_min = max(0, int(group_plan.get("groupReuseBudgetMin", 0)))
    meta_seed = int(manifest.get("meta", {}).get("seed", 0))
    shuffle_seed = meta_seed + 999999
    profile_end_group = max((int(group.get("index", 0)) for group in groups), default=0)

    run_pools: dict[str, list[dict]] = {}
    run_sources: dict[str, str] = {}
    for run in runs:
        run_id = str(run.get("id", "")).strip()
        scored_path_raw = str(run.get("scoredPath", "")).strip()
        if not run_id or not scored_path_raw:
            raise SystemExit("Invalid grouped export manifest run entry.")
        scored_path = resolve_path(scored_path_raw)
        payload = load_json(scored_path)
        run_pools[run_id] = normalize_scored_levels(payload)
        run_sources[run_id] = str(scored_path)

    run_shape_reserve_remaining: Counter[str] = Counter()
    for group in groups:
        raw_shape_targets = group.get("shapeTargets", [])
        if not isinstance(raw_shape_targets, list):
            continue
        for item in raw_shape_targets:
            if not isinstance(item, dict):
                continue
            target_run_id = str(item.get("runId", "")).strip()
            target_levels = int(item.get("targetLevels", 0))
            if not target_run_id or target_levels <= 0:
                continue
            run_shape_reserve_remaining[target_run_id] += target_levels

    exported_levels: list[dict] = []
    exported_groups: list[dict] = []
    next_level_id = 1
    seen_wheels: set[str] = set()
    recent_answer_sets: list[set[str]] = []
    word_last_seen: dict[str, int] = {}
    short_word_signature_last_seen: dict[str, int] = {}
    prior_group_answers: set[str] = set()
    prior_group_word_counts: dict[str, int] = {}
    prior_group_three_letter_signature_counts: dict[str, int] = {}
    for group in groups:
        group_id = str(group.get("id", "")).strip()
        group_index = int(group.get("index", 0))
        target_size = int(group.get("targetSize", 0))
        run_id = str(group.get("runId", "")).strip()
        raw_run_ids = group.get("runIds", [])
        run_ids: list[str] = []
        if isinstance(raw_run_ids, list):
            run_ids = [
                str(candidate_run_id).strip()
                for candidate_run_id in raw_run_ids
                if str(candidate_run_id).strip()
            ]
        if run_id and run_id not in run_ids:
            run_ids.insert(0, run_id)
        if not run_ids and run_id:
            run_ids = [run_id]

        raw_shape_targets = group.get("shapeTargets", [])
        shape_targets: list[dict] = []
        if isinstance(raw_shape_targets, list):
            for item in raw_shape_targets:
                if not isinstance(item, dict):
                    continue
                target_run_id = str(item.get("runId", "")).strip()
                target_levels = int(item.get("targetLevels", 0))
                if not target_run_id or target_levels <= 0:
                    continue
                shape_targets.append(
                    {
                        "runId": target_run_id,
                        "targetLevels": target_levels,
                        "shapeId": str(item.get("shapeId", "")).strip(),
                    }
                )
        wheel_size = int(group.get("wheelSize", 0))
        floor_raw = group.get("frequencyFloor")
        freq_floor = float(floor_raw) if isinstance(floor_raw, (int, float)) else None
        if (
            not group_id
            or not run_ids
            or any(candidate_run_id not in run_pools for candidate_run_id in run_ids)
        ):
            raise SystemExit("Invalid grouped export manifest group entry.")
        if target_size <= 0:
            raise SystemExit(f"Group {group_id} has non-positive target size.")
        required_group_size = min_required_group_size(
            target_size,
            group_size_undershoot_ratio,
        )

        word_cooldown_levels = default_word_cooldown
        if group_index < early_group_count:
            word_cooldown_levels = max(word_cooldown_levels, early_word_cooldown)
        strict_novelty_filters = group_index < strict_novelty_early_groups and bool(
            prior_group_answers
        )

        short_word_cooldown_levels = default_short_word_cooldown
        if group_index < early_group_count:
            short_word_cooldown_levels = max(
                short_word_cooldown_levels,
                early_short_word_cooldown,
            )
        short_word_signature_cooldown_levels = default_short_word_signature_cooldown
        if group_index < early_group_count:
            short_word_signature_cooldown_levels = max(
                short_word_signature_cooldown_levels,
                early_short_word_signature_cooldown,
            )

        min_answers = int(group.get("minAnswers", 1))
        estimated_total_answers = max(1, target_size * max(1, min_answers))
        max_prior_group_reuse_answers = max(
            group_reuse_budget_min,
            int(estimated_total_answers * group_reuse_budget_ratio),
        )
        enforce_cross_pack_word_caps = False
        cross_pack_short_word_group_limit = cross_pack_short_word_max_group_reuse
        cross_pack_long_word_group_limit = cross_pack_long_word_max_group_reuse
        if group_index < cross_pack_early_group_count:
            enforce_cross_pack_word_caps = True
        elif group_index >= cross_pack_late_start_group:
            enforce_cross_pack_word_caps = True
            cross_pack_short_word_group_limit = (
                cross_pack_late_short_word_max_group_reuse
            )
            cross_pack_long_word_group_limit = cross_pack_late_long_word_max_group_reuse
        enforce_three_letter_signature_reuse_cap = (
            group_index < three_letter_signature_early_group_count
        )

        target_avg_freq = profile_target_avg_freq(
            group_index,
            difficulty_profile_start_group,
            profile_end_group,
            difficulty_target_avg_freq_start,
            difficulty_target_avg_freq_end,
            difficulty_target_power,
        )
        min_avg_freq_floor = (
            (target_avg_freq - difficulty_floor_margin)
            if target_avg_freq is not None
            else None
        )
        max_avg_freq_ceiling = (
            (target_avg_freq + difficulty_ceiling_margin)
            if target_avg_freq is not None
            else None
        )

        selected: list[dict] = []
        effective_floor = freq_floor
        if len(run_ids) == 1 and not shape_targets:
            selected, effective_floor = select_group_levels(
                run_pools[run_ids[0]],
                target_size,
                required_group_size,
                f"group={group_id} run={run_ids[0]}",
                freq_floor,
                relax_step,
                relax_steps,
                seen_wheels,
                recent_answer_sets,
                word_last_seen,
                next_level_id,
                overlap_window,
                strict_novelty_filters,
                word_cooldown_levels,
                short_word_len_max,
                short_word_cooldown_levels,
                short_word_signature_last_seen,
                short_word_signature_cooldown_levels,
                short_word_signature_penalty_weight,
                hard_overlap_window,
                hard_overlap_max_shared_words,
                prior_group_answers,
                max_prior_group_reuse_answers,
                prior_group_word_counts,
                global_overuse_short_word_len_max,
                global_overuse_short_weight,
                global_overuse_long_weight,
                target_avg_freq,
                difficulty_target_weight,
                min_avg_freq_floor,
                max_avg_freq_ceiling,
                enforce_cross_pack_word_caps,
                cross_pack_short_word_len_max,
                cross_pack_short_word_group_limit,
                cross_pack_long_word_group_limit,
                enforce_three_letter_signature_reuse_cap,
                prior_group_three_letter_signature_counts,
                three_letter_signature_max_group_reuse,
            )
        else:
            remaining_target = target_size
            for shape_target in shape_targets:
                target_run_id = shape_target["runId"]
                if target_run_id not in run_ids:
                    continue
                local_target = min(remaining_target, int(shape_target["targetLevels"]))
                if local_target <= 0:
                    continue
                shape_selected, shape_floor = select_group_levels(
                    run_pools[target_run_id],
                    local_target,
                    0,
                    f"group={group_id} run={target_run_id}",
                    freq_floor,
                    relax_step,
                    relax_steps,
                    seen_wheels,
                    recent_answer_sets,
                    word_last_seen,
                    next_level_id + len(selected),
                    overlap_window,
                    strict_novelty_filters,
                    word_cooldown_levels,
                    short_word_len_max,
                    short_word_cooldown_levels,
                    short_word_signature_last_seen,
                    short_word_signature_cooldown_levels,
                    short_word_signature_penalty_weight,
                    hard_overlap_window,
                    hard_overlap_max_shared_words,
                    prior_group_answers,
                    max_prior_group_reuse_answers,
                    prior_group_word_counts,
                    global_overuse_short_word_len_max,
                    global_overuse_short_weight,
                    global_overuse_long_weight,
                    target_avg_freq,
                    difficulty_target_weight,
                    min_avg_freq_floor,
                    max_avg_freq_ceiling,
                    enforce_cross_pack_word_caps,
                    cross_pack_short_word_len_max,
                    cross_pack_short_word_group_limit,
                    cross_pack_long_word_group_limit,
                    enforce_three_letter_signature_reuse_cap,
                    prior_group_three_letter_signature_counts,
                    three_letter_signature_max_group_reuse,
                )
                selected.extend(shape_selected)
                run_shape_reserve_remaining[target_run_id] = max(
                    0,
                    run_shape_reserve_remaining.get(target_run_id, 0)
                    - len(shape_selected),
                )
                remaining_target = target_size - len(selected)
                if shape_floor is not None:
                    if effective_floor is None:
                        effective_floor = shape_floor
                    else:
                        effective_floor = min(effective_floor, shape_floor)
                if remaining_target <= 0:
                    break

            if remaining_target > 0:
                merged_pool: list[dict] = []
                for candidate_run_id in run_ids:
                    run_pool = run_pools[candidate_run_id]
                    slack = len(run_pool)
                    if slack <= 0:
                        continue
                    merged_pool.extend(run_pool[:slack])
                merged_selected, merged_floor = select_group_levels(
                    merged_pool,
                    remaining_target,
                    max(0, required_group_size - len(selected)),
                    f"group={group_id} run=merged",
                    freq_floor,
                    relax_step,
                    relax_steps,
                    seen_wheels,
                    recent_answer_sets,
                    word_last_seen,
                    next_level_id + len(selected),
                    overlap_window,
                    strict_novelty_filters,
                    word_cooldown_levels,
                    short_word_len_max,
                    short_word_cooldown_levels,
                    short_word_signature_last_seen,
                    short_word_signature_cooldown_levels,
                    short_word_signature_penalty_weight,
                    hard_overlap_window,
                    hard_overlap_max_shared_words,
                    prior_group_answers,
                    max_prior_group_reuse_answers,
                    prior_group_word_counts,
                    global_overuse_short_word_len_max,
                    global_overuse_short_weight,
                    global_overuse_long_weight,
                    target_avg_freq,
                    difficulty_target_weight,
                    min_avg_freq_floor,
                    max_avg_freq_ceiling,
                    enforce_cross_pack_word_caps,
                    cross_pack_short_word_len_max,
                    cross_pack_short_word_group_limit,
                    cross_pack_long_word_group_limit,
                    enforce_three_letter_signature_reuse_cap,
                    prior_group_three_letter_signature_counts,
                    three_letter_signature_max_group_reuse,
                )
                selected.extend(merged_selected)
                remove_selected_levels_from_run_pools(
                    run_pools,
                    run_ids,
                    merged_selected,
                )
                if merged_floor is not None:
                    if effective_floor is None:
                        effective_floor = merged_floor
                    else:
                        effective_floor = min(effective_floor, merged_floor)

        current_group_answers: set[str] = set()
        for level in selected:
            current_group_answers.update(answer_text_set(level))

        shuffle_rng = random.Random(shuffle_seed + group_index)
        selected = shuffle_levels_with_shape_constraint(selected, shuffle_rng)

        group_level_ids: list[str] = []
        shape_counts: dict[str, int] = {}
        for index_in_group, level in enumerate(selected):
            item = dict(level)
            level_id = f"{group_id}{index_in_group + 1}"
            item["id"] = level_id
            item["campaignIndex"] = next_level_id
            item["groupId"] = group_id
            item["groupIndex"] = group_index
            item["indexInGroup"] = index_in_group
            item["wheelSize"] = wheel_size
            item["wheelShape"] = wheel_shape_id(item)
            shape_counts[item["wheelShape"]] = (
                shape_counts.get(item["wheelShape"], 0) + 1
            )
            min_freq, avg_freq, p25_freq = level_freq_stats(item)
            item["minAnswerFreq"] = round(min_freq, 4)
            item["avgAnswerFreq"] = round(avg_freq, 4)
            item["p25AnswerFreq"] = round(p25_freq, 4)
            exported_levels.append(item)
            group_level_ids.append(level_id)
            next_level_id += 1

        exported_groups.append(
            {
                "id": group_id,
                "index": group_index,
                "wheelSize": wheel_size,
                "targetSize": target_size,
                "runId": run_ids[0],
                "runIds": run_ids,
                "frequencyFloor": freq_floor,
                "effectiveFrequencyFloor": round(effective_floor, 4)
                if effective_floor is not None
                else None,
                "targetAvgAnswerFreq": round(target_avg_freq, 4)
                if target_avg_freq is not None
                else None,
                "shapeTargets": shape_targets,
                "shapeCounts": shape_counts,
                "levelIds": group_level_ids,
            }
        )
        prior_group_answers.update(current_group_answers)

    return exported_groups, exported_levels, manifest_path, group_plan, run_sources


def write_bundle(
    out_path: Path,
    exported_groups: list[dict],
    exported_levels: list[dict],
    manifest_path: Path,
    group_plan: dict,
    run_sources: dict[str, str],
) -> None:
    """Write full bundle with all metadata for analysis tools."""
    licenses = filter_licenses_for_levels(load_licenses())
    out_payload = {
        "meta": {
            "schemaVersion": SCHEMA_VERSION,
            "source": str(manifest_path),
            "levelCount": len(exported_levels),
            "groupPlan": group_plan,
            "runSources": run_sources,
            "licenses": licenses,
        },
        "groups": exported_groups,
        "levels": exported_levels,
    }
    save_json(out_path, out_payload)
    print(
        f"Exported full bundle: {len(exported_levels)} levels, {len(exported_groups)} groups -> {out_path}"
    )


def write_split_files(
    split_dir: Path,
    exported_groups: list[dict],
    exported_levels: list[dict],
) -> None:
    """Write trimmed split files for production runtime use."""
    split_dir.mkdir(parents=True, exist_ok=True)

    levels_by_group: dict[str, list[dict]] = {}
    for level in exported_levels:
        group_id = str(level.get("groupId", ""))
        if group_id not in levels_by_group:
            levels_by_group[group_id] = []
        levels_by_group[group_id].append(level)

    meta_groups: list[dict] = []
    for group in exported_groups:
        group_id = str(group.get("id", ""))
        group_levels = levels_by_group.get(group_id, [])

        # Trim group metadata for production
        meta_group = trim_group_for_production(
            {
                "id": group_id,
                "index": group.get("index"),
                "wheelSize": group.get("wheelSize"),
                "targetSize": group.get("targetSize"),
                "levelCount": len(group_levels),
                "file": f"levels.{group_id}.json",
            }
        )
        meta_groups.append(meta_group)

        # Trim levels for production
        trimmed_levels = [trim_level_for_production(level) for level in group_levels]
        group_file = split_dir / f"levels.{group_id}.json"
        group_payload = {
            "groupId": group_id,
            "levels": trimmed_levels,
        }
        save_json(group_file, group_payload)

    # Write trimmed meta file (minimal metadata for runtime)
    licenses = filter_licenses_for_levels(load_licenses())
    meta_payload = {
        "meta": {
            "schemaVersion": SCHEMA_VERSION,
            "licenses": licenses,
        },
        "groups": meta_groups,
    }
    meta_path = split_dir / "levels._meta.json"
    save_json(meta_path, meta_payload)

    print(
        f"Exported trimmed split files: {len(exported_levels)} levels, {len(exported_groups)} groups -> {split_dir}"
    )
    print(f"  Meta: {meta_path}")
    print(
        f"  Group files: {len(meta_groups)} files (levels.A.json, levels.B.json, ...)"
    )


def main() -> None:
    args = parse_args()

    exported_groups, exported_levels, manifest_path, group_plan, run_sources = (
        grouped_export(args)
    )

    # Always write both bundle and split files
    bundle_path = resolve_path(args.bundle_out)
    write_bundle(
        bundle_path,
        exported_groups,
        exported_levels,
        manifest_path,
        group_plan,
        run_sources,
    )

    split_dir = resolve_path(args.split_dir)
    write_split_files(
        split_dir,
        exported_groups,
        exported_levels,
    )


if __name__ == "__main__":
    main()
