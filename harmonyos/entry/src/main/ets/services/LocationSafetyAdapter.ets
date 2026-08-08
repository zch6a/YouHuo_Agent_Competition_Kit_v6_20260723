// Adapter boundary for HarmonyOS Location Kit / Map Kit / Navi Kit.
// The competition package intentionally keeps SDK-specific calls out of the deterministic core.
// Production integration must request runtime consent, minimize retention, and preserve accuracy metadata.
export interface LocationObservation {
  latitude: number;
  longitude: number;
  accuracyMeters: number;
  occurredAt: string;
}

export class LocationSafetyAdapter {
  static validate(observation: LocationObservation): boolean {
    return observation.latitude >= -90 && observation.latitude <= 90 &&
      observation.longitude >= -180 && observation.longitude <= 180 &&
      observation.accuracyMeters >= 0;
  }
}
