'''
'''
import numpy as np
import sys
from math import sqrt,hypot,atan2,pi,sin,cos
from time import sleep
import cv2
from filterpy.kalman import KalmanFilter
import predictIMM as imm
import predictSpline as spline

class SimpleTracker():
    def __init__(self, imageSizeX = 640, imageSizeY = 480, minMovement = 5, maxMovement = 100):
        self.minm = minMovement
        self.maxm = maxMovement
        self.imageSizeX = imageSizeX
        self.imageSizeY = imageSizeY

        self.maxx = int(imageSizeX/minMovement)
        self.maxy = int(imageSizeY/minMovement)

        self.maxPredicts = 5

        self.tracks0 = {}
        self.identifiedTracks = {}
        self.last     = None
        self.lastHits = {}
        self.estimates = np.zeros((self.imageSizeX, self.imageSizeY), np.int16)
        self.image = self.emptyMovementMatrix()

    def debugImage(self,r,g,b):
        sx,sy = r.shape
        img = np.zeros((sx,sy,3), np.uint8)
        img[:,:,0] = b * 255
        img[:,:,1] = g * 255
        img[:,:,2] = r * 255
        self.image = np.swapaxes(img,0,1)
        return self.image

    def emptyMovementMatrix(self):
        return np.zeros((self.maxx,self.maxy),np.int16)

    def resize(self, width, height):
        self.last = None
        self.maxx = int(width/self.minm)
        self.maxy = int(height/self.minm)

    def setMinMovement(self, newMinMovement):
        while self.imageSizeX % newMinMovement != 0:
            newMinMovement += 1

        self.minm = newMinMovement
        self.resize(self.maxx, self.maxy)

    def setMaxMovement(self, newMaxMovement):
        self.maxm = newMaxMovement

    def trackBoxes(self, vis, boxes, dt=0.1):
        print("==========================================")
        pts = np.zeros(2*len(boxes)).reshape(-1,2)
        szs = np.zeros(len(boxes)).reshape(-1,1)

        for i,a in enumerate(boxes):
            pts[i] = [a[0]+(a[2]-a[0])/2,a[1]+(a[3]-a[1])/2]
            #pts[i] = [(a[3]-a[1])/2,(a[2]-a[0])/2]
            szs[i] = [(a[2]-a[0])*(a[3]-a[1])]

        #pts = np.array(([a[2]-a[0])/2,(a[3]-a[1])/2 for a in boxes]).reshape(-1, 2)
        #szs = np.array(([a[2]-a[0])*(a[3]-a[1]) for a in boxes]).reshape(-1, 2)

        self._trackEngine(dt)
        self._findNewTracks(pts, szs, dt)
        return self.identifiedTracks

    def trackContours(self, vis, pts, szs, dt=0.1):
        print("==========================================")
        self._trackEngine(dt)
        self._findNewTracks(pts, szs, dt)
        return self.identifiedTracks

    def trackKeypoints(self, vis, keypoints, dt=0.1):
        print("==========================================")
        pts = np.array([pt.pt for pt in keypoints]).reshape(-1, 2)
        szs = np.array([pt.size for pt in keypoints]).reshape(-1, 1)
        self._trackEngine(dt)
        self._findNewTracks(pts, szs, dt)
        return self.identifiedTracks

    # first stage of tracking process
    def _trackEngine(self, dt):
        #estimates   = self.emptyMovementMatrix()
        estimates = np.zeros((self.imageSizeX, self.imageSizeY), np.int16)
        # simple tracks
        new_tracks = {}
        # container for real coordinates
        hits = np.array(self.lastHits.values()).reshape(-1,3)

        # >>> debug
        #print("hits: %d %s" % (len(hits),np.array2string(hits)))
        # <<< debug

        # start with the longest track
        sorted=self.identifiedTracks.items()
        sorted.sort(key = lambda item: item[1].prio, reverse=True)
        for (ix,iy),ttrack in sorted:
            # find tracks to update
            if len(hits) > 0:
                if self.estimates[ix,iy] > 0:
                    print("%d,%d estimation found!" % (ix,iy))
                i = ttrack.findHit(hits[::,:2:])
                if(i >= 0):
                    # update track and mask new input
                    ttrack.update(hits[i,0], hits[i,1], hits[i,2], dt)
                    estimates = self.updateMask(estimates, int(hits[i,0]), int(hits[i,1]), self.minm, self.minm)
                    hits = np.delete(hits,i,axis=0)

            # make a new bet
            xest,yest = ttrack.predict(dt)
            # >> debug
            ttrack.printTrack()
            # << debug

            # end track if estimates are out of boundaries
            if xest < 0 or xest >= self.imageSizeX:
                ttrack.predicts = self.maxPredicts + 1
            if yest < 0 or yest >= self.imageSizeY:
                ttrack.predicts = self.maxPredicts + 1
            # remove obsolete tracks
            if ttrack.predicts > self.maxPredicts:
                del self.identifiedTracks[ix,iy]
                continue

            # search new hits for candidates to update
            # tracks with len == 3 are brandnew and can be ignored
            #if len(hits) > 0 and len(ttrack.tr) > 3:
            #    # find nearest hit
            #    i = ttrack.findHit(hits[::,:2:])
            #    if i >= 0:
            #        # update track and mask new input
            #        ttrack.update(hits[i,0], hits[i,1], hits[i,2], dt)
            #        # invalidate the used hit
            #        hits = np.delete(hits,i,axis=0)

            # generate new estimation matrix
            xred = int(xest / self.minm)
            yred = int(yest / self.minm)
            if xred >= self.maxx:
                xred = self.maxx -1
            if yred >= self.maxy:
                yred = self.maxy - 1

            new_tracks[int(xest),int(yest)] = ttrack
            estimates = self.updateMask(estimates, int(xest), int(yest), ttrack.sx, ttrack.sy)


        self.identifiedTracks   = new_tracks
        self.estimates = estimates

    # Occupy positions in mask matrix
    def updateMask(self, mask, x, y, dx, dy):
            # truncate to array boundaries
            xmin = x - dx
            xmax = x + dx
            if(xmin < 0): xmin = 0
            if(xmax >= self.imageSizeX): xmax = self.maxx - 1

            # truncate to array boundaries
            ymin = y - dy
            ymax = y + dy
            if(ymin < 0): ymin = 0
            if(ymax >= self.imageSizeY): ymax = self.maxy - 1

            # occupy area
            mask[xmin:xmax,ymin:ymax] += 1

            return mask

    # second stage of tracking process
    def _findNewTracks(self, new_pts_vector, new_szs_vector, dt):
        #scaled_pts = new_pts_vector * 1.0 / self.minm
        current = self.emptyMovementMatrix()
        # container for real coordinates
        hits = {}
        # simple tracks
        new_tracks = {}

        # fill the actual movement matrix
        for (x,y),size in zip(new_pts_vector, new_szs_vector):
            # search in a movement matrix which has a min-movement granularity
            xx = int(x / self.minm)
            yy = int(y / self.minm)

            # the size of the movement matrix may not fit exactly
            # this case will produces more hits in the last column/row
            if xx >= self.maxx:
                xx = self.maxx -1
            if yy >= self.maxy:
                yy = self.maxy - 1

            # update the movement matrix
            if(self.estimates[x,y] == 0):
                current[xx,yy] += 1
            else:
                print("%d,%d is masked out!" % (x,y))

            # keep position of original coordinates in movement matrix
            # !!! ignore double hits
            #if not hits.has_key((x,y)):
            #    hits[x,y] = []
            #hits[x,y].append((int(xorg),int(yorg)))
            hits[xx,yy] = [(int(x),int(y),size)]

        # determine movement between two frames
        if self.last is not None:
            # update the count of new occurences
            diff = current - self.last
            #                 r      g        b
            #self.debugImage(diff, current, self.last)

            # find the nearest ancestor for newly detected movement vector (diff > 0)
            changes = np.transpose(np.nonzero(diff > 0))

            # sort from center to margin
            #center = np.array([self.maxx/2,self.maxy/2])
            #center_distance = abs(changes - center).max(-1).reshape(-1,1)
            #sorted_changes = np.hstack((changes, center_distance)).reshape(-1,3)
            #changes = sorted_changes[sorted_changes[:,2].argsort()]

            # remember hits from the last frame
            ancestors = np.array(self.lastHits.values()).reshape(-1,3)
            # we don't need the old sizes any longer (remove column 2)
            ancestors = np.delete(ancestors,2,axis=1)

            # walk through new change matrix
            for xx,yy in changes:
                # generate the real coordinates
                for xnew,ynew,size in hits[xx,yy]:
                    # find nearest point in ancestors
                    xold,yold = self.find_ancestor((xnew,ynew), ancestors)
                    # add a point to the track
                    if xold >= 0:
                        # check for an existing track which ends at the ancestor
                        if self.tracks0.has_key((xold,yold)):
                            tr = self.tracks0[xold,yold]
                        else:
                            tr = []

                        tr.append([xnew,ynew])
                        # >>> debug
                        if len(tr) > 1:
                            sys.stdout.write("track: ")
                            for x,y in tr:
                                sys.stdout.write("  %d,%d -> " %(x,y))
                            print("")
                        # <<< debug

                        # limit track length
                        if len(tr) > 10:
                            del tr[0]

                        # prepare sophisticated tracks stuff
                        if self.identifiedTracks.has_key((xold,yold)):
                            # this case should be masked by self.esitmates!
                            print("UNALLOWED UPDATE!")
                            ttrack = self.identifiedTracks[xold,yold]
                            ttrack.update(xnew,ynew,size,dt)
                        else:
                            # add a mature track for further investigation
                            if len(tr) == 3:
                                self.identifiedTracks[xnew,ynew] = track(tr,size,dt,self.minm,self.maxm)
                            else:
                                # add current track to tracking list
                                new_tracks[xnew,ynew] = tr[:]

        self.last     = current
        self.lastHits = hits
        self.tracks0  = new_tracks


    def find_ancestor(self, new_pts, old_pts):
        # compute the distance to each ancestor
        dist = np.abs(old_pts - new_pts).max(-1)
        # too fast movement shall be ignored
        good = dist < self.maxm

        # find the nearest ancestor
        dmin   = self.maxm
        ancest = (-1,-1)
        for (x,y), d, in_range in zip(old_pts, dist, good):
            if in_range:
                #print("xo: %d, yo: %d  d: %d" % (x,y,d))
                if d < dmin:
                    dmin   = d
                    ancest = (x,y)
            else:
                print("%d,%d out of range" % (x,y))

        # >>> debug
        #if dmin < self.maxm:
        #    xnew,ynew = new_pts
        #    print("new: %d,%d -> %d,%d (dist: %d)" % (ancest[0],ancest[1],xnew,ynew,dmin))
        # <<< debug

        return ancest

    def stage1(self, arg):
        pass
'''
    a sophisticated track supported by Kalman prediction
'''
#import predictKalman as pd

class track:
    track_names = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    tindex      = 0
    def enum(**enums):
        return type('Enum', (), enums)
    types = enum(NOISE=1, MOVER=2, EATER=3)

    def __lt__(self, other):
        return self.prio < other.prio

    def __del__(self):
        print("destructor: [%s]" % (self.name))

    def __init__(self, old_track, size, dt=.04, min_movement=5, max_movement=30):
        self.x    = old_track[-1][0]
        self.y    = old_track[-1][1]
        self.prio = len(old_track)

        self.szs = size
        self.tr  = old_track[:]
        # >>> debug
        self.ptr = old_track[:]
        # <<< debug

        #    the track identity
        self._setIdentity()
        self.predicts = 0
        self.sx = max_movement / 2
        self.sy = max_movement / 2
        self.maxm = max_movement
        self.minm = min_movement
        self.dpi = pi/4.0

        # setup Kalman filter
        #self.km = spline.filterSpline(self.tr,dt=dt)
        #self.sx = self.km.xspl.get_residual()
        #self.sy = self.km.yspl.get_residual()
        # omega = an / v (an := accelleration normal to tangent)
        # p : covariance
        # r_std : process noise variance
        omega = dt
        # estimate initial direction
        if self.x - old_track[0][0] >= 0:
            omega = -omega

        self.km = imm.filterIMM(dt=dt, omega=omega, p=50.0, r_std=0.1, q_std=0.1)
        for x,y in self.tr:
            self.km.update(x,y)
        self.px = self.x
        self.py = self.y
        self.updateDirection()

    def findHit(self, hits):
        prediction = np.array([self.px,self.py])
        prediction.resize(1,2)
        #direction  = hits - prediction
        direction  = prediction - hits
        distance   = np.abs(direction).max(-1)
        minindex   = np.argmin(distance,axis=0)
        mindist    = np.amin(distance)


        # check if target is in right direction
        angle_maxdiff = self.dpi
        angle2hit     = atan2(hits[minindex][1]-self.y, hits[minindex][0]-self.x)
        angle_diff    = abs(self.angle - angle2hit)
        if angle_diff > angle_maxdiff:
            print("[%s] angle: %4.2f > %4.2f!" % (self.name, angle_diff, angle_maxdiff))
            minindex = -1
        else:
            # check if target is in valuable range
            dist_max  = self.sx + self.sy
            if mindist > dist_max:
                print("[%s] mindist: %4.2f > %4.2f!" % (self.name, mindist, dist_max))
                minindex = -1

        return minindex

    def updateDirection(self):
        # make direction vector using the last prediction
        if self.predicts == 0:
            self.direction = np.array([self.x - self.tr[-2][0],
                                    self.y - self.tr[-2][1]])
        else:
            self.direction = np.array([self.px - self.x,
                                       self.py - self.y])

        self.angle = atan2(self.direction[1],self.direction[0])
        self.updateSearchRange()

    def updateSearchRange(self):
        #self.sx = self.km.xspl.get_residual()
        #self.sy = self.km.yspl.get_residual()

        # may be this is too simple. take sigmaXX and sigmaYY and multiply by a factor
        # TODO: THIS IS NOT WORKING WELL :-( (I had better results with a fixed value)
        #covaXX = self.km.bank.P[0,0]
        #covaYY = self.km.bank.P[3,3]
        #self.sx = 2.0 * self.maxm * covaXX + self.minm / 2.0
        #self.sy = 2.0 * self.maxm * covaYY + self.minm / 2.0

        # adapt search range to last 2 * prediction
        if self.predicts == 0:
            self.sx = 2 * abs(self.x - self.tr[-2][0])
            self.sy = 2 * abs(self.y - self.tr[-2][1])
        else:
            self.sx = 2 * abs(self.px - self.x)
            self.sy = 2 * abs(self.py - self.y)

        if self.sx > self.maxm / 2:
            self.sx = self.maxm / 2
        if self.sy > self.maxm / 2:
            self.sy = self.maxm / 2

        # compute covariance ellipse
        #P = np.array([[self.km.bank.P[0,0], self.km.bank.P[0,3]],
        #              [self.km.bank.P[3,0], self.km.bank.P[3,3]]])
        #U,s,v = np.linalg.svd(P)
        #self.sx = 6.0 * sqrt(s[0]) # +/- 3 + sigma
        #self.sy = 6.0 * sqrt(s[1]) # +/- 3 * sigma
        #self.sx = 6.0 * s[0] # +/- 3 + sigma**2
        #self.sy = 6.0 * s[1] # +/- 3 * sigma**2

    def update(self, xnew, ynew, sznew, dt=0.1):
        print("[%s] update %d,%d" %(self.name, xnew, ynew))
        self.x = xnew; self.y = ynew
        self.szs = sznew
        self.predicts = 0
        self.km.update(xnew,ynew)
        self.tr.append([xnew,ynew])
        self.prio += 1
        self.updateDirection()
        #return (self.px,self.py)
        return

    def predict(self, dt):
        self.predicts += 1
        xnew,ynew = self.km.predict(dt)
        print("[%s] predict %d,%d" %(self.name, xnew, ynew))
        # >>> debug
        self.ptr.append([xnew,ynew])
        # <<< debug
        self.mu = self.km.mu_max
        self.px = xnew
        self.py = ynew
        self.updateDirection()
        return (xnew,ynew)

    def noMeasurement(self, dt):
        self.predicts += 1
        xnew,ynew = self.km.predict(dt)
        self.km.update(xnew,ynew)
        self.tr.append((xnew,ynew))
        return (xnew,ynew)

    def showTrack(self, vis, color):
        r = int(self.sx+self.sy)

        x0 = int(self.x)
        y0 = int(self.y)

        # show track
        pts = np.int32(self.tr)
        cv2.polylines(vis, [pts], False, (220,0,0))
        for (x,y) in pts:
            cv2.drawMarker(vis, (int(x), int(y)), (255,0,0), cv2.MARKER_CROSS,5)
        cv2.drawMarker(vis, (x0, y0), (255,0,0), cv2.MARKER_TRIANGLE_UP,10)


        # show prediction
        ppts = np.int32(self.ptr)
        cv2.polylines(vis, [ppts], False, (0,0,220))
        for (x,y) in ppts:
            cv2.drawMarker(vis, (int(x), int(y)), (0,0,255), cv2.MARKER_TILTED_CROSS,5)
        cv2.drawMarker(vis, (int(self.px), int(self.py)), (0,0,255), cv2.MARKER_TRIANGLE_DOWN,10)

        #cv2.circle(vis, (int(self.px), int(self.py)), 1, (0,0,255), 1)
        startAngle = np.degrees(self.angle - self.dpi/2.0)
        endAngle = np.degrees(self.angle + self.dpi/2.0)
        cv2.ellipse(vis, (x0, y0), (r, r), 0.0, startAngle, endAngle, (0,0,200), 2)

        if self.predicts < 2:
            tcolor = (0,255,0)
            tsize = 1
        else:
            tcolor = (0,0,255)
            tsize = 2

        cv2.putText(vis, self.name, (x0, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.5,tcolor,tsize)

    def printTrack(self):
        sys.stdout.write("[%s]:" %(self.name))
        for x,y in self.tr:
            sys.stdout.write("  %d,%d -> " %(x,y))

        print(" px:%d py:%d (#%d sx:%4.2f sy:%4.2f)" %(self.px,self.py,self.predicts,self.sx, self.sy))

    def _setIdentity(self):
        self.name = track.track_names[track.tindex]
        track.tindex += 1
        if track.tindex >= len(track.track_names):
            track.tindex = 0
        self.type = track.types.NOISE