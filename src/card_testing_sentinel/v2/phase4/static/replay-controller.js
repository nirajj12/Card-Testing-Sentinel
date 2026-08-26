export class ReplayController {
  constructor(onChange) {
    this.onChange = onChange;
    this.history = [];
    this.position = -1;
    this.timer = null;
    this.speed = 1000;
  }

  push(item) {
    this.history.push(item);
    this.position = this.history.length - 1;
    this.emit();
  }

  previous() {
    if (this.position > 0) this.position -= 1;
    this.emit();
  }

  nextRecorded() {
    if (this.position < this.history.length - 1) this.position += 1;
    this.emit();
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

  play(step) {
    this.pause();
    this.timer = window.setInterval(step, this.speed);
  }

  pause() {
    if (this.timer) window.clearInterval(this.timer);
    this.timer = null;
  }

  setSpeed(value) {
    this.speed = Number(value);
  }

  emit() {
    this.onChange(this.current(), this.position, this.history.length);
  }
}
