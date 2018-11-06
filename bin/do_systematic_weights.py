from __future__ import print_function

import os, sys
import numpy as np
import pylab as plt
import healpy as hp
from astropy.io import fits
from astropy.table import Table
from scipy.optimize import minimize
import argparse

class MultiLinearFit:

    def __init__(self, data_ra=None, data_dec=None, data_we=None, 
                       rand_ra=None, rand_dec=None, rand_we=None,
                       maps=['STAR_DENSITY',
                             'SKY_Z', 
                             'AIRMASS', 
                             'EBV', 
                             'DEPTH_Z', 
                             'PSF_Z', 
                             'W1_MED', 
                             'W1_COVMED'], 
                       fit_maps=None, nbins_per_syst=10):
        ''' Systematic fits 

        ''' 

        #-- If fit_maps is None, fit all maps 
        #-- Otherwise, define indices of maps to be fitted
        if fit_maps is None:
            fit_maps = maps
            fit_index = np.arange(len(maps))
        else:
            fit_index = []
            for i in range(len(maps)):
                if maps[i] in fit_maps:
                    fit_index.append(i)
            fit_index = np.array(fit_index)

        print('Using the following maps:      ', maps)
        print('Fitting for the following maps:', fit_maps)

        if not self.read_systematics_maps(maps=maps): sys.exit()
 
        self.fit_index = fit_index

        self.data_ra = data_ra
        self.data_dec= data_dec
        self.data_we = data_we

        self.rand_ra = rand_ra
        self.rand_dec = rand_dec
        self.rand_we = rand_we

        self.prepare(nbins=nbins_per_syst)

    def read_systematics_maps(self, \
        infits='/mnt/lustre/bautista/software/eboss_clustering/etc/'+\
               'SDSS_WISE_imageprop_nside512.fits', \
        maps=None):
        
        a = fits.open(infits)[1].data
        nsyst = len(maps)
        npix  = a.size
        syst = np.zeros((nsyst, npix)) 
        
        for i in range(len(maps)):
            try:
                syst[i] = a.field(maps[i])
            except:
                print('ERROR reading %s. Available choices:'%maps[i], a.names) 
                return False

        w = np.isnan(syst)
        syst[w] = hp.UNSEEN

        #####-- this is from old code and might be useful         
        ##-- normalize star density into units per deg2 
        #allsyst[0] *= (12*nside**2)/(4*np.pi*(180**2/np.pi**2))
        #
        ##-- modify nside of maps if needed
        #if nside!=nsideh:
        #    nallsyst = np.zeros((nmaps, 12*nside**2))
        #    for i in range(nmaps):
        #        nallsyst[i] = hp.ud_grade(allsyst[i], nside, \
        #                        order_in='NESTED', order_out='NESTED')
        #    allsyst = nallsyst

        self.maps = syst 
        self.maps_names = maps
        self.maps_suffix = maps
        self.nside = hp.npix2nside(npix) 
        self.nmaps = nsyst
        self.nest = False
        return True

    def plot_systematic_map(self, index):

        syst = self.maps[index]
        name = self.maps_names[index]
        w = syst != hp.UNSEEN
        hp.mollview(syst, nest=self.nest, title=name, 
                    min=np.percentile(syst[w], 1), 
                    max=np.percentile(syst[w], 99.))

    def get_pix(self, ra, dec):
        return hp.ang2pix(self.nside, \
                          (-dec+90.)*np.pi/180, \
                          ra*np.pi/180, \
                          nest=self.nest)

    def get_map_values(self, index, ra, dec):
        pix = self.get_pix(ra, dec)
        return self.maps[index, pix] 

    def get_model(self, pars, syst): 
        ''' Compute model from parameters and systematic values
            Input
            ------
            pars : (fit_index.size+1) vector containing parameters of fit
            syst : (N_galaxies, N_syst) array containing systematic values
        '''
        edges = self.edges
        fit_index = self.fit_index
        #-- model is a linear combination of maps
        #-- first parameters is a constant, others are slopes
        model = pars[0]
        model += np.sum(pars[1:]*(syst[:, fit_index]  -edges[fit_index, 0])/\
                                 (edges[fit_index, -1]-edges[fit_index, 0]), axis=1)
        return model

    def prepare(self, nbins = 10):
        ''' Prepare histograms and cut outlier values of systematics'''

        nmaps = self.nmaps

        data_we = self.data_we
        rand_we = self.rand_we
        n_data = data_we.size
        n_rand = rand_we.size

        #-- assign systematic values to all galaxies and randoms
        data_pix = self.get_pix(self.data_ra, self.data_dec) 
        rand_pix = self.get_pix(self.rand_ra, self.rand_dec) 
        data_syst = self.maps[:, data_pix].T
        rand_syst = self.maps[:, rand_pix].T 

        #-- cut galaxies and randoms with extreme values of systematics
        w_data = np.ones(n_data) == 1
        w_rand = np.ones(n_rand) == 1
        for i in range(nmaps):
            syst_min = np.percentile(rand_syst[:, i], 0.5)
            syst_max = np.percentile(rand_syst[:, i], 99.5)
            w_data &= (data_syst[:, i] > syst_min) & \
                      (data_syst[:, i] < syst_max)
            w_rand &= (rand_syst[:, i] > syst_min) & \
                      (rand_syst[:, i] < syst_max)
        data_syst = data_syst[w_data, :]
        rand_syst = rand_syst[w_rand, :]
        data_we = data_we[w_data]
        rand_we = rand_we[w_rand]

        print('Number of galaxies before/after cut: ', n_data, data_we.size)
        print('Number of randoms  before/after cut: ', n_rand, rand_we.size)

        #-- compute histograms        
        factor = np.sum(rand_we)/np.sum(data_we)
        edges      = np.zeros((nmaps, nbins+1))
        centers    = np.zeros((nmaps, nbins))
        h_data     = np.zeros((nmaps, nbins))
        h_rand     = np.zeros((nmaps, nbins))

        for i in range(nmaps):
            edges[i] = np.linspace(data_syst[:, i].min()-1e-5, \
                                   data_syst[:, i].max()+1e-5, \
                                   nbins+1)
            centers[i] = 0.5*(edges[i][:-1]+edges[i][1:]) 
            h_data[i], _ = np.histogram(data_syst[:, i], bins=edges[i], \
                                        weights=data_we)
            h_rand[i], _ = np.histogram(rand_syst[:, i], bins=edges[i], \
                                        weights=rand_we)

        h_index = np.floor((data_syst   -edges[:, 0])/\
                           (edges[:, -1]-edges[:, 0])*nbins).astype(int)

        self.data_syst = data_syst
        self.rand_syst = rand_syst
        self.data_we = data_we
        self.rand_we = rand_we
        self.factor = factor
        self.edges = edges
        self.centers = centers
        self.h_index = h_index
        self.h_data = h_data
        self.h_rand = h_rand
        
        #-- computing overdensity and error assuming poisson
        self.dens = h_data/h_rand * factor
        self.edens = np.sqrt((h_data   /h_rand**2 + \
                              h_data**2/h_rand**3   )) * factor

    def get_histograms(self, pars=None):
        data_syst = self.data_syst
        data_we = self.data_we
        h_data = self.h_data
        h_rand = self.h_rand
        h_index = self.h_index

        if pars is None:
            pars = np.zeros(self.fit_index.size+1)
            pars[0] = 1.

        we_model = 1/self.get_model(pars, data_syst)

        #-- doing histograms with np.bincount, it's faster
        for i in range(self.nmaps):
            h_data[i] = np.bincount(h_index[:, i], weights=data_we*we_model)

        if pars[0] != 1.:
            self.pars = pars
        self.h_data = h_data

        #-- computing overdensity and error assuming poisson
        self.dens = h_data/h_rand * self.factor
        self.edens = np.sqrt((h_data   /h_rand**2 + \
                              h_data**2/h_rand**3   )) * self.factor

    def get_chi2(self, pars=None):
        self.get_histograms(pars=pars)
        return np.sum((self.dens-1.)**2/self.edens**2)

    def plot_overdensity(self, ylim=[0.75, 1.25],\
                         nbinsh=50):

        centers = self.centers
        names = self.maps_names
        nmaps = self.nmaps
        nbins = centers[0].size
        data_syst = self.data_syst
   
        #-- if the fit has been done, plot both before and after fits 
        pars = [None, self.pars] if hasattr(self, 'pars') else [None]

        #-- setting up the windows
        figsize = (15, 3) if nmaps > 1 else (5,3)
        f, ax = plt.subplots(1, nmaps, sharey=True, figsize=figsize)
        if nmaps == 1:
            ax = [ax] 
        if nmaps > 1: 
            f.subplots_adjust(wspace=0.05, left=0.05, right=0.98, 
                              top=0.98, bottom=0.15)
        ax[0].set_ylim(ylim)

        #-- compute histograms for before/after parameters
        for par in pars:
            self.get_histograms(pars=par)
            dens = self.dens
            edens = self.edens
            for i in range(nmaps):
             
                chi2 = np.sum( (dens[i]-1.)**2/edens[i]**2)
                label = r'$\chi^2_{r}  = %.1f/%d = %.2f$'%\
                     (chi2, nbins, chi2/nbins)

                ax[i].errorbar(centers[i], dens[i], edens[i], \
                                    fmt='.', label=label)
                ax[i].axhline( 1.0, color='k', ls='--')
                ax[i].locator_params(axis='x', nbins=5, tight=True)
                
                #-- add title and legend
                ax[i].legend(loc=0, numpoints=1, fontsize=8)
                ax[i].set_xlabel(names[i])

        #-- overplot histogram (normalizing to the 1/3 of the y-axis)
        for i in range(nmaps):
            h_syst, bins = np.histogram(data_syst[:, i], bins=nbinsh)

            x = 0.5*(bins[:-1]+bins[1:])
            y = h_syst/h_syst.max()*0.3*(ylim[1]-ylim[0])+ylim[0]
            ax[i].step(x, y, where='mid', color='g')

        ax[0].set_ylabel('Density fluctuations')

    def fit_pars(self):

        pars0 = np.zeros(self.fit_index.size+1)
        pars0[0] = 1.

        #-- try to coverge three times at most
        success = False
        ntries = 0
        while success is False and ntries < 3:
            ntries += 1
            print('Fitting parameters - trial #%d of 3'%ntries)
            pars_object = minimize(self.get_chi2, pars0, \
                                   method='Nelder-Mead')
            print(pars_object['message'])
            success = pars_object['success']
            pars0 = pars_object['x']

        self.pars = pars_object['x']
        
        chi2_before = self.get_chi2()
        ndata = self.dens.size
        npars = pars0.size
        rchi2_before = chi2_before/(ndata-0)
        print('Before fit: chi2/(ndata-npars) = %.2f/(%d-%d) = %.3f'%\
               (chi2_before, ndata, 0, rchi2_before ))
        chi2_after = self.get_chi2(self.pars)
        rchi2_after = chi2_after/(ndata-npars)
        print('After fit:  chi2/(ndata-npars) = %.2f/(%d-%d) = %.3f'%\
               (chi2_after, ndata, npars, rchi2_after ))
         
    def get_weights(self, ra, dec):
        pix  = self.get_pix(ra, dec)
        syst = self.maps[:, pix].T 
        if not hasattr(self, 'pars'): 
            self.fit_pars()
        return 1/self.get_model(self.pars, syst)
        


parser = argparse.ArgumentParser()

parser.add_argument('-d', '--data',    
    help='Input data catalog')
parser.add_argument('-r', '--randoms', 
    help='Input random catalog', default=None)
parser.add_argument('-o', '--output', default=None,
    help='Output catalogs name without extension (will create .dat.fits and .ran.fits')
parser.add_argument('--read_maps', nargs='+', 
    help='List of maps to be read.', 
    default=['STAR_DENSITY',
             'AIRMASS',
             'EBV',
             'DEPTH_Z',
             'PSF_Z',
             'W1_MED',
             'W1_COVMED'])
parser.add_argument('--fit_maps', nargs='+', 
    help='List of maps to be fitted. Default fits for all maps.', default=None)
parser.add_argument('--nbins_per_syst', type=int, default=20, 
    help='Number of bins per systematic quantity')
parser.add_argument('--zmin', type=float, default=0.6,
    help='Minimum redshift')
parser.add_argument('--zmax', type=float, default=1.0,
    help='Maximum redshift')
parser.add_argument('--plot_deltas', action='store_true', default=False,
    help='If set, plots the delta vs systematic')
args = parser.parse_args()

print('Reading galaxies from ',args.data)
dat = Table.read(args.data)
if args.randoms is not None:
    ran_file = args.randoms 
else:
    ran_file = args.data.replace('.dat.fits', '.ran.fits')
print('Reading randoms  from ', ran_file)
ran = Table.read(ran_file)


print('Cutting galaxies and randoms between zmin=%.3f and zmax=%.3f'%\
      (args.zmin, args.zmax))
dat = dat[dat['IMATCH']==1]
wd = (dat['Z']>=args.zmin)&\
     (dat['Z']<=args.zmax)&\
     (dat['COMP_BOSS']>0.5) 
wr = (ran['Z']>=args.zmin)&\
     (ran['Z']<=args.zmax)&\
     (ran['COMP_BOSS']>0.5)

data_ra, data_dec = dat['RA'][wd], dat['DEC'][wd]
rand_ra, rand_dec = ran['RA'][wr], ran['DEC'][wr]

data_we = (dat['WEIGHT_CP']*dat['WEIGHT_FKP'])[wd]
rand_we = (ran['COMP_BOSS'])[wr]

m = MultiLinearFit(
        data_ra=data_ra, data_dec=data_dec, data_we=data_we,
        rand_ra=rand_ra, rand_dec=rand_dec, rand_we=rand_we,
        maps=args.read_maps, 
        fit_maps=args.fit_maps, 
        nbins_per_syst=args.nbins_per_syst)
m.fit_pars()


print('Assigning weights to galaxies and randoms')
dat['WEIGHT_SYSTOT_JB'] = m.get_weights(dat['RA'], dat['DEC'])
ran['WEIGHT_SYSTOT_JB'] = m.get_weights(ran['RA'], ran['DEC'])

if args.plot_deltas:
    print('Plotting deltas versus systematics')
    m.plot_overdensity(ylim=[0.5, 1.5])
    plt.show()

if args.output:
    print('Exporting catalogs to ', args.output)
    dat.write(args.output+'.dat.fits', overwrite=True)
    ran.write(args.output+'.ran.fits', overwrite=True)

 