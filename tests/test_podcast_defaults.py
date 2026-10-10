from ermclip.models import JobSpec, Layout, Profile
from ermclip.request import source_context


def test_podcast_default_is_isolated_and_idempotent(settings):
    original = JobSpec(source='podcast.mp4')
    result = source_context(original, settings)
    assert result.profiles[0].layout.preset == 'podcast_hero'
    assert result.profiles[0].captions.preset == 'short_yellow'
    assert result.profiles[0].framing == 'speaker'
    assert original.profiles[0].layout.preset == 'plain'
    assert settings.defaults[0].layout.preset == 'plain'
    assert source_context(result, settings).model_dump() == result.model_dump()


def test_explicit_custom_layout_captions_and_opt_out(settings):
    for profile in [Profile(layout=Layout(preset='reference_window')),
                    Profile(inherit_podcast_style=False),
                    Profile(ratio='16:9', width=1920, height=1080)]:
        result = source_context(JobSpec(source='podcast.mp4', profiles=[profile]), settings)
        assert result.profiles[0].layout == profile.layout
    p = Profile(); p.captions.preset = 'cherry_glow'
    result = source_context(JobSpec(source='podcast.mp4', profiles=[p]), settings)
    assert result.profiles[0].captions.preset == 'cherry_glow'
    assert source_context(JobSpec(source='podcast.mp4', podcast_mode='off'), settings).profiles[0].layout.preset == 'plain'
    assert source_context(JobSpec(source='podcast.mp4', instruction='Keep the full frame'), settings).profiles[0].layout.preset == 'plain'
    assert source_context(JobSpec(source='car.mp4'), settings).profiles[0].layout.preset == 'plain'


def test_keep_full_answer_does_not_disable_speaker_or_thumbnail(settings):
    spec=JobSpec(source='podcast.mp4',podcast_mode='on',instruction='Keep the question and full answer when needed.')
    result=source_context(spec,settings)
    assert result.profiles[0].framing=='speaker'
    assert result.profiles[0].layout.preset=='podcast_hero'
    assert result.profiles[0].captions.preset=='short_yellow'
