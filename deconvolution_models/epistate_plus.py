import numpy as np
from scipy.special import logsumexp
import sys
sys.path.append("/Users/ireneu/PycharmProjects/epiread-tools")
from epiread_tools.naming_conventions import *


class READMeth:
    '''
    Read-based EM Algorithm for Deconvolution of Methylation sequencing
    '''
    pseudocount = 1e-10

    def __init__(self, mixtures, lambda_t, theta_high, theta_low, num_iterations=50, convergence_criteria=0.001, alpha=None):
        '''
        :param mixtures: data for deconvolution. c reads by m cpg sites
        :param lambda_t: prob of epistateH per cell type
        :param theta_high: methylation prob under epistateH per cpg
        :param theta_low: methylation prob under epistateL per cpg
        :param num_iterations: maximum iterations for em
        :param convergence_criteria: stopping criteria for em
        '''
        self.x = mixtures
        self.x_c_v = [(~(x == NOVAL)).any() for x in self.x]
        self.Lt = self.add_pseudocounts(lambda_t)
        self.thetaH = theta_high
        self.thetaL = theta_low
        self.filter_no_coverage()

        self.log_Lt =  [np.log(t) for t in self.Lt]
        self.log_one_minus_Lt = [np.log(1-t) for t in self.Lt]

        self.num_iterations = num_iterations
        self.convergence_criteria = convergence_criteria
        self.x_c_m = [(x == METHYLATED) for x in self.x]
        self.x_c_u = [(x == UNMETHYLATED) for x in self.x]
        self.t = self.Lt[0].shape[0]
        c, m = [arr.shape[0] for arr in self.x], [arr.shape[1] for arr in self.x]
        self.c, self.m = np.sum(c), np.sum(m)
        self.alpha = alpha
        self.log_x_given_H = self.calc_x_given_prob(self.thetaH)
        self.log_x_given_L = self.calc_x_given_prob(self.thetaL)

    def filter_no_coverage(self):
        self.x = self.x[self.x_c_v]
        self.Lt = self.Lt[self.x_c_v]
        self.thetaH = self.thetaH[self.x_c_v]
        self.thetaL = self.thetaL[self.x_c_v]


    def add_pseudocounts(self, list_of_arrays):
        '''
        avoid prob 0 and 1 for logarithm
        :param arr: array of probability
        :return: array without 0 and 1
        '''
        for arr in list_of_arrays:
            arr[arr==1] -= self.pseudocount
            arr[arr==0] += self.pseudocount
        return list_of_arrays

    def log_likelihood(self, alpha): # this works
        ll = 0
        for window in range(len(self.x)):
            log_lambda = self.log_Lt[window]
            log_one_minus_lambda = self.log_one_minus_Lt[window]
            logH = self.log_x_given_H[window]
            logL = self.log_x_given_L[window]
            t_c = np.ones((log_lambda.shape[0], logH.shape[0]))
            a = logsumexp([(log_lambda*t_c.T).T+logH*t_c, (log_one_minus_lambda*t_c.T).T+logL*t_c], axis=0)
            b = logsumexp(((np.log(alpha)*t_c.T).T + a), axis=0)
            ll += np.sum(b)
        return ll

    def calc_x_given_prob(self, prob): #this works
        '''
        since thetas are given this
        is a constant
        :return: log P(x|prob)
        '''
        res = []
        for window in range(len(self.x)):
            x_c_m =  self.x_c_m[window].astype(int)
            x_c_u = self.x_c_u[window].astype(int)
            log_prob = np.nan_to_num(np.log(prob[window]).T)
            log_one_minus_prob = np.nan_to_num(np.log(1 - prob[window]).T)
            res.append((np.matmul(x_c_m, log_prob) + np.matmul(x_c_u, log_one_minus_prob)).T)
        return res

    def calc_mu(self, z):
        mu = []
        for window in range(len(self.x)):
            t_c = np.ones((self.alpha.shape[0], self.x_c_m[window].shape[0]))
            log_high = logsumexp((self.log_Lt[window]*t_c.T).T + self.log_x_given_H[window]*t_c + np.log(z[window]), axis=0)
            log_low = logsumexp((self.log_one_minus_Lt[window]*t_c.T).T + self.log_x_given_L[window]*t_c + np.log(z[window]), axis=0)
            log_mu = log_high - logsumexp([log_high, log_low], axis=0)
            mu.append(np.exp(log_mu))
        return mu

    def calc_z(self, mu, alpha):
        z = []
        for window in range(len(self.x)):
            T, C = alpha.shape[0], self.x_c_m[window].shape[0]
            mu_win = np.tile(mu[window], (T,1))
            Lt_win = np.tile(self.Lt[window], (C,1)).T
            alpha_win = np.tile(alpha, (C,1)).T
            z_win = mu_win*Lt_win*alpha_win + (1-mu_win)*(1-Lt_win)*alpha_win
            z_win = z_win/np.sum(z_win, axis=0)
            z.append(z_win)
        return z

    def init_alpha(self):
        if self.alpha is None:
            alpha = np.random.uniform(size=(self.t))
            alpha /= np.sum(alpha)
            self.alpha = alpha

    def init_mu_no_log(self):
        mu = []
        for window in range(len(self.thetaH)):
            t_c = np.ones((self.alpha.shape[0], self.x_c_m[window].shape[0]))
            #TODO: there's probably a nice linear algebra way to do this
            high = np.sum(np.exp(self.log_x_given_H[window]) * (self.alpha*self.Lt[window]*t_c.T).T, axis=0)
            low = np.sum(np.exp(self.log_x_given_L[window]) * (self.alpha*(1-self.Lt[window])*t_c.T).T, axis=0)
            new_mu = high/(high+low)
            mu.append(new_mu)
        return mu

    def maximization(self, z):
        '''
        argmax value of cel type proportions
        :param z: cell type indicator
        :return: alpha
        '''
        all_z = np.hstack(z)
        new_alpha = np.sum(all_z, axis=1) / self.c
        new_alpha /= np.sum(new_alpha)
        return new_alpha

    def test_convergence(self, new_alpha):
        alpha_diff = np.mean(abs(new_alpha - self.alpha)) / np.mean(abs(self.alpha))
        return alpha_diff < self.convergence_criteria

    def em(self):
        '''
        perform EM for a given number of iterations
        :return: cell type proportions, log-likelihood
        '''
        self.init_alpha()
        mu = self.init_mu_no_log()
        ll = []
        i = 0
        for i in range(self.num_iterations):
            ll.append(self.log_likelihood(self.alpha))
            self.z = self.calc_z(mu, self.alpha)
            new_alpha = self.maximization(self.z)
            mu = self.calc_mu(self.z)

            if i and self.test_convergence(new_alpha):
                break

            else:  # set current evaluation of alpha and gamma
                self.alpha = new_alpha
        return self.alpha, i
