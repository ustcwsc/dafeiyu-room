"""Guide a voiced contour towards a score without discarding its inflection."""
import numpy as np


def guide_pitch(sound, manipulation, note_times, notes_hz):
    from parselmouth.praat import call
    from scipy.ndimage import gaussian_filter1d

    analysis = sound.to_pitch(time_step=.01, pitch_floor=65, pitch_ceiling=650)
    voiced = analysis.selected_array["frequency"] > 0
    if not np.any(voiced):
        return
    times = analysis.xs()
    log_f0 = np.interp(times,times[voiced],np.log2(analysis.selected_array["frequency"][voiced]))
    # Keep local contours and suppress octave jumps in the analysis.
    detail = np.clip(log_f0-gaussian_filter1d(log_f0,10),-.13,.13)
    targets = np.log2(notes_hz)[np.maximum(0,np.searchsorted(note_times,times,side="right")-1)]
    curve = 2**(gaussian_filter1d(targets,3,mode="nearest")+.65*detail)
    tier = call(manipulation,"Extract pitch tier")
    call(tier,"Remove points between",0,sound.duration)
    for t,hz in zip(times[voiced],curve[voiced]):
        call(tier,"Add point",t,hz)
    call([tier,manipulation],"Replace pitch tier")
