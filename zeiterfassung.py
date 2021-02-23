#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys, select
import os
from   os.path import expandvars

import argparse
import datetime
from   termcolor import colored
from babel.dates import format_date

import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper


def main(db=None):
    parser = argparse.ArgumentParser(
        formatter_class=lambda prog:
            argparse.RawTextHelpFormatter(prog, width=90, max_help_position=27))

    date_group = parser.add_argument_group(description="bestimmt den zu bearbeitenden Tag; falls nichts gesetzt, nutze heute:")
    date_group.add_argument('--date', type=str, default=False, help="zu bearbeitender Tag im ISO Format (z.B. 1970-12-31)")
    date_group.add_argument('-d', '--day', type=int, default=False, help="bestimmt den zu bearbeitenden Tag")
    date_group.add_argument('-m', '--month', type=int, default=False, help="bestimmt den zu bearbeitenden Monat")
    date_group.add_argument('-y', '--year', type=int, default=False, help="bestimmt das zu bearbeitende Jahr")

    day_group = parser.add_argument_group(description="definiert den Arbeitstag:")
    day_group.add_argument('-s', '--start', type=str, nargs='?', default=False, help="setzt Arbetisbeginn, falls ohne Argument: nutze jetzt")
    day_group.add_argument('-e', '--end', type=str, nargs='?', default=False, help="setzt Arbeitsende, falls ohne Argument: nutze jetzt")

    day_group.add_argument('-p', '--pause', type=int, nargs='?', default=False, help="Pausenzeit in Minuten")

    day_group.add_argument('-c', '--comment', type=str, nargs='*', default=None, help="optionaler Kommentar zum Eintrag")

    day_group.add_argument('--multi_day', type=str, default=False, help="ermöglicht mehrere Einträge pro Tag")

    parser.add_argument('-w', '--work_time', type=str, default='8:00', help="Arbeitspensum pro Tag; Format H:MM")

    parser.add_argument('-r', '--round', type=int, default='1', help="Arbeitsbeginn/-ende auf ROUND Minuten runden")

    parser.add_argument('--db_path', type=str, default=os.path.dirname(__file__)+"/data/", help="Ort, an dem die In- und Output Files liegen")
    parser.add_argument('--user', type=str, default="GJ", help="zu bearbeitender Mitarbeiter")
    parser.add_argument('--export', nargs='*', default=[], help="schreibt erfasste Zeiten in gegebenen Formaten;\nunterstützt: [yml, xls]")

    parser.add_argument('--remove', action='store_true', default=False, help="entfernt den momentanen Tag aus der DB")
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help="prints the all stored days for the user instead of only current month")
    parser.add_argument('-q', '--quiet', action='store_true', default=False, help="nur Fehler ausgeben")
    parser.add_argument('--expand', action='store_false', default=None, help="expandiert die anderweitig kompakte Ausgabe der erfassten Zeiten")

    out_of_office_group = parser.add_mutually_exclusive_group()
    out_of_office_group.add_argument('-u', '--urlaub', action='store_true', default=None, help="deklariert den Tag als Urlaubstag:\nkeine Arbeit erwartet, kein Saldo verbraucht")
    out_of_office_group.add_argument('-z', '--zeitausgleich', action='store_true', default=None, help="keine Arbeitszeit, Saldo wird um reguläre Zeit veringert")

    args = parser.parse_args()

    if args.urlaub:
        try:
            args.comment[0:0] = ["Urlaub;"]
        except TypeError:
            args.comment = ["Urlaub"]
    elif args.zeitausgleich:
        try:
            args.comment[0:0] = ["Zeitausgleich;"]
        except TypeError:
            args.comment = ["Zeitausgleich"]

    db_file = args.db_path + args.user + "_Zeiterfassung.yml"
    try:
        db = db or yaml.load(open(db_file), Loader=Loader) or {}
    except FileNotFoundError:
        db = {}

    now = datetime.datetime.now()

    date             = args.date or str(now.date())
    year, month, day = (int(t) for t in date.split('-'))
    year             = args.year or year
    month            = args.month or month
    day              = args.day or day
    week             = datetime.date(year, month, day).isocalendar()[1]

    hours, minutes = (int(t) for t in str(now.time()).split(':')[:-1])
    minutes        = minutes - minutes % args.round  # rounding minutes to last quarter
    round_down     = datetime.datetime(year, month, day, hours, minutes, 00)
    round_up       = datetime.datetime(year, month, day, hours, minutes, 00) + datetime.timedelta(minutes=args.round)

    # get the desired day and create its data base entry if not there yet
    this_day = get_day_from_db(db, year, month, week, day)

    if args.remove:
        if args.multi_day:
            this_day = this_day[args.multi_day]
        this_day.update(dict((k, {}) for k in this_day))
    elif not (args.start is False and args.end is False and args.pause is False and args.comment is None):
        this_day = update_day(this_day, args, round_up, round_down)

    # recursively remove empty dictionary leaves
    clean_db(db)

    # sort database by date
    db = sort_db(db)

    # calculate over-time saldos on a daily, weekly and monthly basis
    calculate_saldos(db, work_time=args.work_time)

    kw = 0
    if not args.quiet:
        for y, y_data in db.items():
            if y == "Arbeitszeitkonto":
                print("\n{:<30} {:>21}".format(colored("Arbeitszeitkonto", "blue"), colored(db["Arbeitszeitkonto"], "red" if db["Arbeitszeitkonto"][0]=="-" else "green")))
                continue
            for m, m_data in y_data.items():
                if m == "Jahressaldo":
                    continue
                if m == month or args.verbose:
                    # print(colored("\n{:^48}".format( format_time(date(y, m, 1), "MMMM YYYY", locale="de")), "blue"))
                    print( colored("\n{:^48}".format( format_date(datetime.date(y, m, 1), "MMMM YYYY", locale="de") ), "blue") )
                    for w, w_data in m_data.items():
                        if w == "Monatssaldo":
                            print("\n{:<20}           {:>21}".format(colored("Monatssaldo", "blue"), colored(w_data, "red" if w_data[0]=="-" else "green")))
                            continue
                        kw = w
                        print("\n", colored("KW {:>2}".format(kw), "blue"), " {:^5} {:^5} {:5} {:^4} {:>5}  {}".format("von", "bis", "Pause", "AZ", "Saldo", "Kommentar/AZK"), sep="")
                        for d, d_data in w_data.items():
                            if d == "Wochenstunden":
                                print("{:<22}         {:>6} {:>14} {:>23}".format(colored("Wochenstunden", "blue"), d_data, colored(w_data["Wochensaldo"], "red" if w_data["Wochensaldo"][0]=="-" else "green"), colored(w_data["AZK"], "red" if w_data["AZK"][0]=="-" else "green")))
                                continue
                            if d == "Wochensaldo" or d == "AZK":
                                continue
                            print("{:3}   {:5} {:5} {:^5} {:>4} {:>14}  {}".format(
                                d,
                                d_data["start"]              if "start"       in d_data else "",
                                d_data["end"]                if "end"         in d_data else "",
                                d_data["pause"]              if "pause"       in d_data else "",
                                d_data["Arbeitszeit"]        if "Arbeitszeit" in d_data else "",
                                colored(d_data["Tagessaldo"] if "Tagessaldo"  in d_data else "", "red" if (d_data["Tagessaldo"][0] if "Tagessaldo" in d_data else "")=="-" else "green"),
                                d_data["comment"]            if "comment"     in d_data else ""
                            ))

        # if not args.verbose:
        #     print("Arbeitszeitkonto:", db["Arbeitszeitkonto"])
    yaml.dump(db, open(db_file, mode="w"), Dumper=Dumper)

    for ending in args.export:
        export_file_name = args.db_path + args.user + \
            f"_Zeiterfassung_{year}_{month:02}.{{}}"
        if ending in ["yml", "yaml"]:
            yaml.dump(db[year][month],
                      open(export_file_name.format("yml"), mode="w"),
                      Dumper=Dumper)
        if ending in ["xls", "xlsx", "excel"]:
            export_excel(db, year, month, export_file_name.format("xlsx"))

    return db


def get_day_from_db(db, year, month, week, day):
    # get the desired day and create its data base entry if not there yet
    # iteratively creates nested dicts up to the desired depth
    while True:
        try:
            return db[year][month][week][day]
        except KeyError:
            db_temp = db
            try:
                for k in [year, month, week, day]:
                    if k:
                        db_temp = db_temp[k]
            except KeyError:
                db_temp[k] = {}


def update_day(this_day, args, round_up, round_down):
    if args.multi_day:
       # if current day was previously a one-block day, reset the relevant
       # entries (they will be removed later by `clean_db`)
       # Also set the entry node for the multi-day
       for a in ["start", "end", "pause", "comment", args.multi_day]:
           this_day[a] = {}
       this_day = this_day[args.multi_day]
    else:
       # if `this_day` was previously declared multi-day,
       # reset the multi-day fields (they will be removed later by `clean_db`)
       for a, b in this_day.items():
           if type(b) == dict:
               this_day[a] = {}

    # populate the desired day with the given information
    # The logic for `start` (and `end`) is as follows:
    # - By default, `start` is `False`, so if it doesn't show up in the list of CL
    #   arguments, the if-statement does not Trigger
    # - If `start` is used in the CL and followed by a time stamp, use that time
    #   as starting time
    # - If `start` is used in the CL but without any parameter, `args.start` will
    #   be `None` and the or-statement will use the current time
    if args.start is not False:
        if "start" in this_day:
            if args.start is None:
                print("neue Startzeit muss explizit angegeben werden --start HH:MM")
            else:
                this_day["start"] = args.start or format_time(round_down.time())
        else:
            this_day["start"] = args.start or format_time(round_down.time())
    if args.end is not False:
        if "end" in this_day:
            if args.end is None and round_up.time() < datetime.datetime.strptime(this_day["end"], '%H:%M').time():
                print("neue Endzeit muss explizit angegeben werden --end HH:MM")
            else:
                this_day["end"] = args.end or format_time(round_up.time())
        else:
            this_day["end"] = args.end or format_time(round_up.time())
    if args.pause is not False:
        if args.pause is None:
            start = datetime.datetime.now()
            print("[Enter] drücken um die Pause zu beenden")
            i = None
            while not i:
                i, o, e = select.select( [sys.stdin], [], [], 1 )
                print(" {:02}:{:02}".format(int((datetime.datetime.now() - start).total_seconds()/60), int((datetime.datetime.now() - start).total_seconds())%60), end="\r")
            if "pause" in this_day:
                this_day["pause"] += int((datetime.datetime.now() - start).total_seconds()/60)
            else:
                this_day["pause"] = int((datetime.datetime.now() - start).total_seconds()/60)
        else:
            this_day["pause"] = args.pause

    if args.comment is not None:
        # if `comment` flag is set but argument empty, try to remove present comment
        if args.comment:
            this_day["comment"] = " ".join(args.comment)
        else:
            try:
                del this_day["comment"]
            except KeyError:
                pass

    # ensure proper order of the start, end, pause tokens
    for key in ["start", "end", "pause", "comment"]:
        # Note: `comment` does get pushed to the end later anyway but do it here
        # aswell for clarity
        try:
            temp = this_day[key]
            del this_day[key]
            this_day[key] = temp
        except KeyError:
            pass


def clean_db(db):
    try:
        for k, v in db.items():
            if isinstance(v, dict):
                clean_db(v)
            if v == {} or "saldo" in str(k) or "Arbeit" in str(k) or "Woche" in str(k) or "Arbeitszeitkonto" in str(k) or "AZK" in str(k):
                del db[k]
    except RuntimeError:
        clean_db(db)


def sort_db(old_db):
    '''sorts the DB numerically by year -> month -> week -> day
    this assumes all the saldo entries have been removed by `clean_db` just before;
    otherwise, this will break

    preserves the order of strings, i.e. "start" - "end" - "pause", and multi-day tokens,
    it's your responsibility to sort them properly (you can always move them around in
    the .yml file later)
    '''
    try:
        new_db = {}
        for k in sorted(int(l) for l in old_db):
            new_db[k] = sort_db(old_db[k])
        return new_db
    except ValueError:
        # if `l` is a string that cannot be converted to integer, we hit the maximum
        # depth; return the original, not resorted dict
        return old_db


def calculate_saldos(db, work_time="8:00"):
    # calculate over-time saldos on a daily, weekly and monthly basis
    work_hours, work_minutes           = (int(t) for t in work_time.split(':'))
    today_year, today_month, today_day = (int(t) for t in str(datetime.datetime.now().date()).split('-'))

    kw, dow = [0, 0]
    azk     = datetime.timedelta()
    az      = datetime.timedelta()
    week_total = datetime.timedelta()
    for y, year in db.items():
        year_balance = datetime.timedelta()
        for m, month in year.items():
            month_balance = datetime.timedelta()
            for w, week in month.items():
                if kw != w:
                    kw, dow      = [w, 0]
                    week_total   = datetime.timedelta()
                    week_balance = datetime.timedelta()
                for d, day in week.items():
                    if d == "Wochenstunden":
                        continue
                    dow += 1
                    if ("end" in day) or ([d, m, y] == [today_day, today_month, today_year]):
                        try:
                            # assume this is a multi-part day
                            day_balance = datetime.timedelta()
                            for part in day.values():
                                day_balance += calc_balance(part)

                        except TypeError:
                            # if not, `part["start"]` should throw a `TypeError`
                            # -> "string indices must be integers"
                            # so, go on with the single-part approach
                            day_balance = calc_balance(day)

                        # print(d, m, format_timedelta(day_balance))
                        day["Arbeitszeit"] = format_timedelta(day_balance)
                        week_total        += day_balance

                    # check if we are on a working day
                    # TODO check for legal holidays?
                    if "end" in day:
                        if datetime.datetime(y, m, d).weekday() < 5:
                            day_balance -= datetime.timedelta(hours=work_hours, minutes=work_minutes)
                        else:
                            # we are on a weekend day; make this clear in the comment
                            # and set the expected work time to zero
                            day_balance = calc_balance(day)
                            try:
                                if "wochenende" not in day["comment"].lower():
                                    day["comment"] = "Wochenende; " + day["comment"]
                            except KeyError:
                                day["comment"] = "Wochenende"
                        day["Tagessaldo"] = format_timedelta(day_balance)
                    else:
                        day_balance = datetime.timedelta()
                        if "comment" in day and ("urlaub" in day["comment"].lower() or "feiertag" in day["comment"].lower()):
                            week_total += datetime.timedelta(hours=work_hours, minutes=work_minutes)
                        if "comment" in day and "zeitausgleich"in day["comment"].lower():
                            day_balance -= datetime.timedelta(hours=work_hours, minutes=work_minutes)
                    week_balance  += day_balance
                    month_balance += day_balance
                    az            += day_balance

                    # if there is a comment, move it to the back of the day-dict
                    try:
                        comm = day["comment"]
                        del day["comment"]
                        day["comment"] = comm
                    except KeyError:
                        pass


                if dow >=5 or [today_day, today_month, today_year]==[d,m,y]:
                    week["Wochenstunden"] = "{:02d}:{:02d}".format(int((week_total.days*24)+(week_total.seconds/60/60)), int(((week_total.days*24)+(week_total.seconds/60/60))%1*60+0.5))
                    week["Wochensaldo"]   = format_timedelta(week_balance)
                    week["AZK"]           = format_timedelta(az)
                

            month["Monatssaldo"] = format_timedelta(month_balance)
            year_balance        += month_balance
        year["Jahressaldo"]  = format_timedelta(year_balance)
        azk                 += year_balance
    db["Arbeitszeitkonto"] = format_timedelta(azk)


def format_time(t):
    return str(t)[:-3]


def format_timedelta(td):
    if td < datetime.timedelta(0):
        return '-' + format_timedelta(-td)
    else:
        return format_time(td)


def calc_balance(day):
    try:
        start = day["start"]
        try:
            end = day["end"]
        except KeyError:
            end = str(datetime.datetime.now().time())[:5]
        try:
            pause = day["pause"]
        except KeyError:
            pause = 0
        return (datetime.datetime.strptime(end, '%H:%M') - datetime.datetime.strptime(start, '%H:%M') - datetime.timedelta(minutes=pause))
    except KeyError:
        return datetime.timedelta()


def export_excel(db, year, month, file_name):
    try:
        from pandas import DataFrame
        from calendar import month_name
    except ImportError:
        print("ImportError")
        return None

    date_col         = []
    start_col        = []
    end_col          = []
    break_col        = []
    h_incl_break_col = []
    Tagesstunden_col = []
    week_hours_col   = []
    week_diff_col    = []
    month_diff_col   = []
    comment_col      = []
    kw, dow          = [0, 0]

    for w, week in db[year][month].items():
        if kw != w:
            kw, dow = [w, 0]
            week_hours = datetime.timedelta(0)
        if w == "Monatssaldo":
            continue
        for d, day in week.items():
            if d == "Wochensaldo" or d == "AZK":
                continue
            if d == "Wochenstunden":
                week_hours_col[-1] = day
                continue
            if "comment" in day and ( "urlaub" in day["comment"].lower() or "zeitausgleich" in day["comment"].lower() ):
                date_col.append(datetime.date(year, month, d).isoformat())
                start_col.append("")
                end_col.append("")
                break_col.append("")
                h_incl_break_col.append("")
                Tagesstunden_col.append("")
                week_hours_col.append("")
                week_diff_col.append("")
                month_diff_col.append("")
                comment_col.append(day["comment"])
                continue
            
            dow           += 1
            hours, minutes = day['Arbeitszeit'].split(':')
            day_hours      = datetime.timedelta(hours=int(hours), minutes=int(minutes))
            week_hours    += day_hours

            try:  # single-entry day
                if "end" in day:
                    date_col.append(datetime.date(year, month, d).isoformat())
                    start_col.append(day["start"])
                    end_col.append(day["end"])
                    if "pause" in day:
                        break_col.append(day["pause"])
                        h_incl_break_col.append(format_timedelta(day_hours + datetime.timedelta(minutes=day["pause"])))
                    else:
                        break_col.append("")
                        h_incl_break_col.append(format_timedelta(day_hours))

                    Tagesstunden_col.append("")
                    try:
                        comment_col.append(day["comment"])
                    except KeyError:
                        comment_col.append("")
                else:
                    date_col.append(datetime.date(year, month, d).isoformat())
                    start_col.append(day["start"])
                    end_col.append("")
                    break_col.append("")
                    h_incl_break_col.append(format_timedelta(day_hours))
                    Tagesstunden_col.append("")
                    comment_col.append("")
            except (TypeError, KeyError):  # multi-day entry
                for t, token in day.items():
                    if "Tagessaldo" == t or "Arbeitszeit" == t:
                        continue
                    date_col.append(datetime.date(year, month, d).isoformat())
                    start_col.append(token["start"])
                    end_col.append(token["end"])
                    break_col.append(token["pause"])
                    h_incl_break_col.append("")
                    Tagesstunden_col.append("")
                    try:
                        comment_col.append(": ".join([t, token["comment"]]))
                    except KeyError:
                        comment_col.append("")

            Tagesstunden_col[-1] = day["Arbeitszeit"]
            week_hours_col.append("")
            week_diff_col.append("")
            month_diff_col.append("")

        s                = week_hours.total_seconds()
        hours, remainder = divmod(s, 3600)
        minutes, seconds = divmod(remainder, 60)
        # week_hours_col[-1] = f"{int(hours)}:{int(minutes):02d}"
        if "Wochensaldo" in week:
            week_diff_col[-1] = week["Wochensaldo"]
        else:
            week_diff_col[-1] = ""

    df = DataFrame({'Datum':         date_col         + [""],
                    'Beginn':        start_col        + [""],
                    'Ende':          end_col          + [""],
                    'Pause':         break_col        + [""],
                    'h inkl. Pause': h_incl_break_col + [""],
                    'Tagesstunden':  Tagesstunden_col + [""],
                    'Wochenstunden': week_hours_col   + [""],
                    'Wochensaldo':   week_diff_col    + [""],
                    'Monatssaldo':   month_diff_col   + [db[year][month]["Monatssaldo"]],
                    'Kommentar':     comment_col      + [month_name[month]]})

    df.to_excel(file_name, sheet_name='Tabelle1', index=False)


if __name__ == "__main__":
    db = main()
