from app.media import _duo_speaker_pairs


def test_third_speaker_replaces_the_silent_host_not_the_other_speaker():
    pairs = _duo_speaker_pairs([
        [6.0, 5.0, 0.1],
        [6.0, 0.1, 5.0],
        [6.0, 0.1, 5.0],
    ])
    assert pairs[0] == (0, 1)
    assert pairs[1] == pairs[2] == (0, 2)


def test_new_speaker_can_replace_either_pane_and_fourth_host_can_join():
    pairs = _duo_speaker_pairs([
        [6.0, 5.0, 0.1, 0.1],
        [0.1, 5.0, 6.0, 0.1],
        [0.1, 5.0, 6.0, 0.1],
        [0.1, 0.1, 6.0, 5.0],
        [0.1, 0.1, 6.0, 5.0],
    ])
    assert pairs[2] == (2, 1)
    assert pairs[4] == (2, 3)
    assert all(len(set(pair)) == 2 for pair in pairs)


def test_reaction_or_silence_does_not_cause_camera_switches():
    pairs = _duo_speaker_pairs([
        [6.0, 5.0, 0.1],
        [6.0, 0.1, 7.0],
        [6.0, 5.0, 0.1],
        [0.0, 0.0, 0.0],
        [0.1, 0.1, 0.2],
    ])
    assert pairs == [(0, 1)] * 5


def test_visible_speakers_do_not_swap_panes_when_their_volume_changes():
    pairs = _duo_speaker_pairs([
        [6.0, 5.0, 0.1],
        [3.0, 9.0, 0.1],
        [9.0, 3.0, 0.1],
    ])
    assert pairs == [(0, 1)] * 3
