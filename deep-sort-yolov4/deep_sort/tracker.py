# vim: expandtab:ts=4:sw=4
from __future__ import absolute_import
import numpy as np
from . import kalman_filter
from . import linear_assignment
from . import iou_matching
from .track import Track
from math import sqrt


class Tracker:
    """
    This is the multi-target tracker.

    Parameters
    ----------
    metric : nn_matching.NearestNeighborDistanceMetric
        A distance metric for measurement-to-track association.
    max_age : int
        Maximum number of missed misses before a track is deleted.
    n_init : int
        Number of consecutive detections before the track is confirmed. The
        track state is set to `Deleted` if a miss occurs within the first
        `n_init` frames.

    Attributes
    ----------
    metric : nn_matching.NearestNeighborDistanceMetric
        The distance metric used for measurement to track association.
    max_age : int
        Maximum number of missed misses before a track is deleted.
    n_init : int
        Number of frames that a track remains in initialization phase.
    kf : kalman_filter.KalmanFilter
        A Kalman filter to filter target trajectories in image space.
    tracks : List[Track]
        The list of active tracks at the current time step.

    """

    def __init__(self, metric, max_iou_distance=0.9, max_age=40, n_init=11):
        self.metric = metric
        self.max_iou_distance = max_iou_distance
        self.max_age = max_age
        self.n_init = n_init

        self.kf = kalman_filter.KalmanFilter()
        self.tracks = []
        self._next_id = 1
        self.Covered_lists = []

    def predict(self):
        """Propagate track state distributions one time step forward.

        This function should be called once every time step, before `update`.
        """
        for track in self.tracks:
            track.predict(self.kf)

        for i, track in enumerate(self.Covered_lists):

            track[2] += 1
            if track[2] >= 140:
                self.Covered_lists.pop(i)


    def update(self, detections):
        """Perform measurement update and track management.

        Parameters
        ----------
        detections : List[deep_sort.detection.Detection]
            A list of detections at the current time step.

        """
        # Run matching cascade.
        matches, unmatched_tracks, unmatched_detections = \
            self._match(detections)

        track_covered = [t.to_tlwh() for t in self.tracks]
        # Update track set.
        for track_idx, detection_idx in matches:
            self.tracks[track_idx].update (self.kf, detections[detection_idx])
        for track_idx in unmatched_tracks:
            self.tracks[track_idx].is_Covered(track_covered, 0.75)
            self.tracks[track_idx].mark_missed()
            if self.tracks[track_idx].state == 3 and self.tracks[track_idx].time_since_update == 1:
                print("DELETE ID", self._next_id)
                self._next_id -= 1

        for detection_idx in unmatched_detections:
            self._initiate_track(detections[detection_idx])

        for t in self.tracks:
            if t.Covered:
                self.Covered_lists.append([t.track_id, t.to_tlwh(), t.cover_frame])
        self.tracks = [t for t in self.tracks if not t.is_deleted() and not t.Covered]


        # Update distance metric.
        active_targets = [t.track_id for t in self.tracks if t.is_confirmed()]
        features, targets = [], []
        for track in self.tracks:
            if not track.is_confirmed():
                continue
            features += track.features
            targets += [track.track_id for _ in track.features]
            track.features = []
        self.metric.partial_fit(
            np.asarray(features), np.asarray(targets), active_targets)

    def _match(self, detections):

        def gated_metric(tracks, dets, track_indices, detection_indices):
            features = np.array([dets[i].feature for i in detection_indices])
            targets = np.array([tracks[i].track_id for i in track_indices])
            cost_matrix = self.metric.distance(features, targets)
            cost_matrix = linear_assignment.gate_cost_matrix(
                self.kf, cost_matrix, tracks, dets, track_indices,
                detection_indices)

            return cost_matrix

        # Split track set into confirmed and unconfirmed tracks.
        confirmed_tracks = [
            i for i, t in enumerate(self.tracks) if t.is_confirmed()]
        unconfirmed_tracks = [
            i for i, t in enumerate(self.tracks) if not t.is_confirmed()]

        # Associate confirmed tracks using appearance features.
        matches_a, unmatched_tracks_a, unmatched_detections = \
            linear_assignment.matching_cascade(
                gated_metric, self.metric.matching_threshold, self.max_age,
                self.tracks, detections, confirmed_tracks)

        # Associate remaining tracks together with unconfirmed tracks using IOU.
        iou_track_candidates = unconfirmed_tracks + [
            k for k in unmatched_tracks_a if
            self.tracks[k].time_since_update == 1]
        unmatched_tracks_a = [
            k for k in unmatched_tracks_a if
            self.tracks[k].time_since_update != 1]
        matches_b, unmatched_tracks_b, unmatched_detections = \
            linear_assignment.min_cost_matching(
                iou_matching.iou_cost, self.max_iou_distance, self.tracks,
                detections, iou_track_candidates, unmatched_detections)

        matches = matches_a + matches_b
        unmatched_tracks = list(set(unmatched_tracks_a + unmatched_tracks_b))
        return matches, unmatched_tracks, unmatched_detections



    def _initiate_track(self, detection):
        x1, y1, w1, h1 = detection.tlwh
        mean, covariance = self.kf.initiate(detection.to_xyah())
        is_OLD, OLD_ID = self.new_id_track ([x1, y1, w1, h1])
        if is_OLD:
            self.tracks.append(Track(
                mean, covariance, OLD_ID, self.n_init, self.max_age,
                    detection.feature))
        else:
            self.tracks.append(Track(
                mean, covariance, self._next_id, self.n_init, self.max_age,
                detection.feature))
            self._next_id += 1


    def new_id_track(self, detection):
        if self.Covered_lists:
            x1, y1, w1, h1 = detection
            for i, cover in enumerate(self.Covered_lists):
                x2, y2, w2, h2 = cover[1]
                D = sqrt ((x2 - x1) ** 2 + (y2 - y1) ** 2)
                print(" ------ DEGUB D", cover[0], D)
                print(x1, y1, w1, h1)
                if 1 < D <= 60:
                    print(" ------ DEBUG OLD ID")
                    self.Covered_lists.pop(i)
                    return True, cover[0]
        return False, -1
