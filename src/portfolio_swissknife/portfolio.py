import numpy as np
import pandas as pd
import yfinance as yf
import time
from .metrics import *
from .optimization import *
from .plotting import *
from .estimation import *

class Engine:
    '''
    Initializes the Engine superclass that supersedes both the Portfolio and Risk Model classes. Defines the general
    data structure that fetches and stores data and retrieves states. Also sets the period for analysis that is
    encapsulated within the class and a new class has to be instantiated in order to carry out analysis in different
    time frames.
    '''
    def __init__(self, securities: list):
        self.securities = securities
        self.size = int(len(self.securities))
        self.prices = None
        self.returns = None
        self.period = None

    def __add__(self, other):
        raise NotImplementedError

    def __sub__(self, other):
        raise NotImplementedError

    def set_period(self, period: tuple):
        self.period = period

    #class methods
    def get_prices(self, frequency = 'daily'):
        try:
            assert (self.period is not None)
            self.prices = yf.download(self.securities,
                                      start = self.period[0],
                                      end = self.period[1],
                                      frequency = frequency)
            self.prices = self.prices.loc[:, ('Adj Close', slice(None))]
            self.returns = self.prices.pct_change().dropna().to_numpy()
            self.dates = self.prices.index[1:]
            self.custom_prices = False

            if frequency == 'daily':
                self.trading_days = 252
            elif frequency == 'monthly':
                self.trading_days = 12

        #todo implement checker - no missing data!

        except AssertionError:
            print('You need to provide start and end dates!')

    def set_custom_prices(self, df, frequency = 'daily'):
        self.prices = df
        self.period = (df.index[0].strftime('%Y-%m-%d'), df.index[-1].strftime('%Y-%m-%d'))
        self.returns = self.prices.pct_change().dropna().to_numpy()
        self.dates = self.prices.index[1:]
        self.estimation_period = 0 #initialize to 0 until a method sets it to x > 0
        self.custom_prices = True


        if frequency == 'daily':
            self.trading_days = 252
        elif frequency == 'monthly':
            self.trading_days = 12

    def _get_state(self, t_0, t_1):
        #slicing the engine data structure
        assert t_0 <= t_1
        return self.returns[t_0 : t_1, :]

class Portfolio(Engine):
    def __init__(self, securities : list, start_weights = None):
        super().__init__(securities)

        #initialize estimation methods to simple returns
        self.estimation_method = [mean_return_historic, sample_cov]

        if start_weights is not None:
            self.start_weights = start_weights
        else:
            #initialize to equal weights
            self.start_weights = np.empty(self.size, dtype=float)
            self.start_weights.fill(1/self.size)

        self.start_weights = self.start_weights.reshape(self.size, 1)
        self.benchmark = None

    def __call__(self):
        return f'This is a Portfolio spanning from {self.period[0]} to {self.period[1]}.' \
               f' It consists of {self.size} securities.'

    def __len__(self):
        raise NotImplementedError

    def set_benchmark(self, benchmark: str):
        self.benchmark = yf.download(benchmark,
                                     start = self.period[0],
                                     end = self.period[1])
        self.benchmark = self.benchmark.loc[:,'Adj Close']
        self.benchmark = self.benchmark.iloc[(-len(self.dates)-1):]
        self.benchmark = self.benchmark.pct_change().dropna().to_numpy()

    def set_discount(self, discount: str):
        self.discount = yf.download(discount,
                                    start = self.period[0],
                                    end = self.period[1])
        self.discount = self.discount.loc[:, 'Adj Close'].reindex(index=self.dates).fillna(method='ffill')
        self.discount = self.discount.to_numpy()
        #
        self.discount /= 100

    def set_transaction_cost(self, transaction_cost = '0.005'):
        self.transaction_cost = transaction_cost

    def set_estimation_method(self, function, moment: int):
        self.estimation_method[moment - 1] = function

    def set_constraints(self, constraint_dict = None, default = True):
        if default:
            self.constraints = {'long_only': True,
                                'leverage': 1,
                                'normalizing': True}
        else:
            self.constraints = constraint_dict

    def historical_backtest(self, models = ['EW', 'GMV', 'RP'], frequency = 22,
                 estimation_period = 252, *args, **kwargs):

        #caching backtest attributes
        self.weighting_models = models
        self.estimation_period = estimation_period

        self.backtest = {}
        self.estimates = {'exp_value' : [],
                          'cov_matrix' : []}

        self.estimates = self._rolling_estimate(self.estimates, self.estimation_period, frequency)

        #backtest logic
        for model in models:
            model_results = {'weights': [],
                             'returns': [],
                             'trade_dates':[],
                             'opt_time': 0.}
            tic = time.perf_counter()
            num_rebalance = 0

            for trade in range(estimation_period, self.returns.shape[0], frequency):
                #solve optimization starting with start_weights
                mu = self.estimates['exp_value'][num_rebalance]
                sigma = self.estimates['cov_matrix'][num_rebalance]
                r_est = self._get_state(trade - estimation_period, trade)

                if num_rebalance == 0:
                    w_t = self.start_weights
                    w_prev = w_t

                #mean-variance specifications
                elif model == 'MSR':
                    ir_kwargs = {'r_f' : self.discount[trade - self.estimation_period: trade],
                                 'num_periods' : self.trading_days,
                                 'ratio_type': 'sharpe'}
                    w_t = self._rebalance(mu , sigma, w_prev, model, r_est = r_est, maximum = True,
                                          function = information_ratio, function_kwargs = ir_kwargs)
                elif model == 'MES':
                    var_kwargs = {'alpha' : 0.05,
                                  'exp_shortfall': True,
                                  'dist': 't'}
                    w_t = self._rebalance(mu , sigma, w_prev, model, r_est = r_est, maximum = False,
                                          function = var, function_kwargs = var_kwargs)
                elif model == 'MDD':
                    w_t = self._rebalance(mu, sigma, w_prev, model, r_est = r_est, maximum = False,
                                          function = max_drawdown, function_kwargs=None)

                else:
                    w_t = self._rebalance(mu, sigma, w_prev, model)
                    #cache
                w_prev = w_t

                #todo implement transaction costs
                #get current returns and compute out of sample portfolio returns
                r_t = self._get_state(trade, trade + frequency)
                r_p = np.dot(r_t, w_t)

                model_results['returns'].append(r_p)
                model_results['weights'].append(w_t)
                model_results['trade_dates'].append(self.dates[trade])
                num_rebalance += 1

            model_results['returns'] = np.vstack(model_results['returns'])
            toc = time.perf_counter()
            model_results['opt_time'] = toc - tic
            self.backtest[model] = model_results

    def get_backtest_report(self, display_weights = True, *args, **kwargs):
        #construct the dataframe
        bt_rets =  pd.DataFrame({mod : self.backtest[mod]['returns'].flatten()
                                 for mod in self.weighting_models},
                                index = self.dates[self.estimation_period:])
        bt_rets_cum = (1+bt_rets).cumprod()
        bmark_rets_cum = (1+self.benchmark[self.estimation_period:]).cumprod()

        plot_returns(bt_rets_cum, bmark_rets_cum, *args, **kwargs)

        stats = portfolio_summary(bt_rets, self.discount[self.estimation_period:],
                                  self.benchmark[self.estimation_period:], self.trading_days)
        display(stats)

        #plot the weights
        if display_weights:

            bt_weights = {}
            for mod in self.weighting_models:
                #exclude ew
                if mod != 'EW':
                    bt_weights[mod] = pd.DataFrame(np.concatenate(self.backtest[mod]['weights'],axis=1).T,
                                                   columns = self.securities, index = self.backtest[mod]['trade_dates'])

            #plot the returns
            plot_weights(bt_weights, self.weighting_models, *args, **kwargs)



    def _rebalance(self, mu, sigma, w_prev,
                   opt_problem: str, *args, **kwargs):

        #solve efficient frontier

        if opt_problem == 'MSR' or opt_problem == 'cVAR' or opt_problem == 'MDD' or opt_problem == 'MES':
            self.efficient_frontier = quadratic_risk_utility(mu, sigma, self.constraints,
                                                                  self.size, 100)
        #solve problems
        if opt_problem == 'EW':
            w_opt = np.full((self.size, 1), 1/self.size)
        if opt_problem == 'GMV':
            w_opt = global_minimum_variance(sigma, self.constraints, self.size)
        if opt_problem == 'RP':
            w_opt = risk_parity(sigma,self.constraints, self.size)
        if opt_problem == 'MDR':
            w_opt = max_diversification_ratio(sigma, w_prev, self.constraints)
        if opt_problem == 'MSR':
            w_opt = greedy_optimization(self.efficient_frontier, *args, **kwargs)
        if opt_problem == 'MES':
            w_opt = greedy_optimization(self.efficient_frontier, *args, **kwargs)
        if opt_problem == 'MDD':
            w_opt = greedy_optimization(self.efficient_frontier, *args, **kwargs)


        w_opt = w_opt.reshape(self.size, 1)
        return w_opt

    def _rolling_estimate(self, estimates_dict, estimation_period, frequency, *args, **kwargs):
        for trade in range(estimation_period, self.returns.shape[0], frequency):
            # estimate necessary params
            r_est = super()._get_state(trade - estimation_period, trade)

            for idx, moment in enumerate(estimates_dict.keys()):
                estimates_dict[moment].append(self._estimate(self.estimation_method[idx],
                                                             r_est, *args, **kwargs))
        return estimates_dict

    def _estimate(self, estimator, r_est, *args, **kwargs):
        moment = estimator(r_est, *args, **kwargs)
        return moment

class FactorPortfolio(Portfolio):
    def __init__(self, universe: Portfolio, risk_model, factor: str, start_weights = None):
        self.universe = universe
        self.risk_model = risk_model
        self.returns = self.universe.returns
        self.estimation_method = [mean_return_historic, sample_cov]
        self.dates = self.risk_model.dates
        self.trading_days = self.universe.trading_days
        self.period = self.risk_model.period

        if factor in risk_model.factors:
            self.factor_idx = self.risk_model.factors.index(factor)
        else:
            raise ValueError('Factor not specified in your model!')

        self.size =  self.size = len(self.risk_model.risk_selection['top_idx'][0][:,self.factor_idx])

        if start_weights:
            self.start_weights = start_weights
        else:
            self.start_weights = np.empty(self.size, dtype = float)
            self.start_weights.fill(1/self.size)

    def _get_state(self, t_0, t_1, filter):
        return super(FactorPortfolio, self)._get_state(t_0, t_1)[:, filter]

    def historical_backtest(self, models = ['EW', 'GMV', 'RP'], frequency = 22,
                            estimation_period = 252, *args, **kwargs):

        self.weighting_models = models
        self.estimation_period = estimation_period
        self.backtest = {}
        self.estimates_top = {'exp_value' : [],
                              'cov_matrix' : []}
        self.estimates_bottom = {'exp_value' : [],
                                 'cov_matrix' : []}

        self.estimates_top = self._rolling_estimate(self.estimates_top, self.estimation_period, frequency,
                                                    self.risk_model.risk_selection['top_idx'])

        # backtest logic
        for model in models:
            model_results = {'returns': [],
                             'weights': [],
                             'trade_dates': [],
                             'opt_time': 0.}
            tic = time.perf_counter()
            num_rebalance = 0

            for trade in range(estimation_period, self.returns.shape[0], frequency):
                # solve optimization starting with start_weights
                idx_selected = self.risk_model.risk_selection['top_idx'][num_rebalance][:, self.factor_idx]
                mu = self.estimates_top['exp_value'][num_rebalance]
                sigma = self.estimates_top['cov_matrix'][num_rebalance]
                r_est = self._get_state(trade - estimation_period, trade, idx_selected)

                self.size = len(self.risk_model.risk_selection['top_idx'][num_rebalance][:,self.factor_idx])
                #todo finish the backtest!!!

                if num_rebalance == 0:
                    w_t = self.start_weights

                elif model == 'MDR':
                    raise ValueError('MDR is not supported for FactorPortfolio.')
                # mean-variance specifications
                elif model == 'MSR':
                    ir_kwargs = {'r_f': self.discount[trade - self.estimation_period: trade],
                                 'num_periods': self.trading_days,
                                 'ratio_type': 'sharpe'}
                    w_t = self._rebalance(mu, sigma, w_prev, model, r_est=r_est, maximum=True,
                                          function=information_ratio, function_kwargs=ir_kwargs)
                elif model == 'MES':
                    var_kwargs = {'alpha': 0.05,
                                  'exp_shortfall': True,
                                  'dist': 't'}
                    w_t = self._rebalance(mu, sigma, w_prev, model, r_est=r_est, maximum=False,
                                          function=var, function_kwargs=var_kwargs)
                elif model == 'MDD':
                    w_t = self._rebalance(mu, sigma, w_prev, model, r_est=r_est, maximum=False,
                                          function=max_drawdown, function_kwargs=None)

                else:
                    w_t = self._rebalance(mu, sigma, w_prev, model)
                    # cache
                w_prev = w_t

                # todo implement transaction costs
                # get current returns and compute out of sample portfolio returns
                r_t = self._get_state(trade, trade + frequency, idx_selected)
                r_p = np.dot(r_t, w_t)

                # todo implement short side of the portfolio!!!

                model_results['returns'].append(r_p.flatten())
                model_results['weights'].append(w_t)
                model_results['trade_dates'].append(self.dates[trade])
                num_rebalance += 1

            model_results['returns'] = np.hstack(model_results['returns'])
            toc = time.perf_counter()
            model_results['opt_time'] = toc - tic
            self.backtest[model] = model_results

    @staticmethod
    def plot_compare_factors(portfolio_list: list):
        raise NotImplementedError

    def _rolling_estimate(self, estimates_dict, estimation_period, frequency,
                          security_filter, *args, **kwargs):
        counter = 0
        for trade in range(estimation_period, self.returns.shape[0], frequency):
            # estimate necessary params
            idx_selected = security_filter[counter][:, self.factor_idx]
            r_est = self._get_state(trade - estimation_period, trade, idx_selected)

            for idx, moment in enumerate(estimates_dict.keys()):
                estimates_dict[moment].append(self._estimate(self.estimation_method[idx],
                                                             r_est, *args, **kwargs))
            counter += 1
        return estimates_dict










