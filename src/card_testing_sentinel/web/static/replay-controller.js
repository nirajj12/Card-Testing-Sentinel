/* Playback over recorded demo steps.

   Two fixes over the previous version:
   1. nextRecorded() is now actually reachable, so going back and then forward
      walks the recorded history instead of jumping to the newest step.
   2. Playback uses a self-scheduling timeout that waits for each async step to
      finish, so slow responses can no longer pile up on top of each other, and
      a speed change takes effect on the very next tick. */
export class ReplayController {
  constructor(onChange) {
    this.onChange = onChange;
    this.history = [];
    this.position = -1;
    this.timer = null;
    this.playing = false;
    this.speed = 1000;
  }

  push(item) {
    this.history.push(item);
    this.position = this.history.length - 1;
    this.emit();
  }

  get atStart() {
    return this.position <= 0;
  }

  get atEnd() {
    return this.position >= this.history.length - 1;
  }

  previous() {
    if (this.position > 0) {
      this.position -= 1;
      this.emit();
    }
  }

  nextRecorded() {
    if (this.position < this.history.length - 1) {
      this.position += 1;
      this.emit();
      return true;
    }
    return false;
  }

  current() {
    return this.history[this.position] || null;
  }

  reset() {
    this.pause();
    this.history = [];
    this.position = -1;
    this.emit();
  }

  play(step, onStop) {
    this.pause();
    this.playing = true;
    const tick = async () => {
      if (!this.playing) return;
      let keepGoing = true;
      try {
        keepGoing = (await step()) !== false;
      } catch (error) {
        this.playing = false;
        onStop?.(error);
        return;
      }
      if (!this.playing || !keepGoing) {
        this.playing = false;
        onStop?.(null);
        return;
      }
      this.timer = window.setTimeout(tick, this.speed);
    };
    tick();
  }

  pause() {
    this.playing = false;
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = null;
  }

  setSpeed(value) {
    this.speed = Number(value) || 1000;
  }

  emit() {
    this.onChange(this.current(), this.position, this.history.length);
  }
}
